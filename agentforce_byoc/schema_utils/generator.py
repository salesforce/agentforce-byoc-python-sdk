# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Generate an OpenAPI spec from ``@entry_func`` functions.

Scans a Python source file for functions decorated with ``@entry_func`` (see
:mod:`agentforce_byoc.schema_utils.entry_func`), extracts their signatures and
the ``@requestSchema`` / ``@responseSchema`` classes, and produces an OpenAPI
3.0.0 specification exposing each function as a POST operation with the
``x-sfdc.code-extension`` block used for BYOC Code Extension registration.

The source is parsed at the **AST level** — it is never imported or executed —
so generation is safe to run on untrusted customer code and needs none of the
code's own runtime dependencies. The only dependency here is PyYAML.

Each ``@entry_func`` function must accept exactly one parameter named
``request`` whose type is ``Dict`` (or ``dict``) and must return ``Dict`` (or
``dict``). A bare ``dict`` is only allowed when the corresponding
``@requestSchema`` / ``@responseSchema`` decorator supplies the field types.

Example::

    from agentforce_byoc.schema_utils import generate_schema_yaml

    yaml_str = generate_schema_yaml(
        source_path="main.py", namespace="myOrg", package="myPackage"
    )
"""

from __future__ import annotations

import argparse
import ast
import sys
from typing import Any, Dict, List, Optional, Tuple, cast

# NOTE: PyYAML is imported lazily inside the functions that need it
# (generate_schema_yaml / load_config), NOT at module top level. This module is
# re-exported from agentforce_byoc.schema_utils, which generated packages import
# just to get the @entry_func / @requestSchema / @responseSchema decorators.
# Those packages don't depend on PyYAML (the AST-based generator is a CLI/dev
# tool, not a runtime dependency), so a top-level `import yaml` would crash the
# package at import time with ModuleNotFoundError.

# ---------------------------------------------------------------------------
# Python-type → OpenAPI type mapping
# ---------------------------------------------------------------------------

_SIMPLE_TYPE_MAP: Dict[str, Dict[str, str]] = {
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "str": {"type": "string"},
    "bool": {"type": "boolean"},
}

_DEFAULT_NAMESPACE = "myOrg"
_DEFAULT_PACKAGE = "myPackage"


def python_type_to_openapi(type_annotation: Any) -> Dict[str, Any]:
    """Convert a Python type annotation (str or AST node) to an OpenAPI schema dict.

    Supports simple types (``int``, ``str``, …), generic containers
    (``List[int]``, ``Dict[str, int]``), and arbitrarily nested combinations
    (``Dict[str, Dict[str, List[int]]]``).
    """
    if isinstance(type_annotation, ast.Subscript):
        return _ast_node_to_openapi(type_annotation)

    if isinstance(type_annotation, str):
        if type_annotation in _SIMPLE_TYPE_MAP:
            return dict(_SIMPLE_TYPE_MAP[type_annotation])
        if type_annotation in ("list", "List"):
            return {"type": "array"}
        if type_annotation in ("dict", "Dict"):
            return {"type": "object"}
        raise ValueError(f"Unsupported type annotation: {type_annotation}")

    if isinstance(type_annotation, ast.Name):
        return python_type_to_openapi(type_annotation.id)

    raise ValueError(f"Unsupported type annotation: {ast.dump(type_annotation)}")


def _ast_node_to_openapi(
    node: ast.expr,
    class_map: Optional[Dict[str, "ClassSchema"]] = None,
) -> Dict[str, Any]:
    """Recursively convert an AST annotation node to an OpenAPI schema."""
    if isinstance(node, ast.Name):
        if class_map and node.id in class_map:
            return _build_class_openapi_schema(class_map[node.id], class_map)
        return python_type_to_openapi(node.id)

    if isinstance(node, ast.Constant):
        return python_type_to_openapi(type(node.value).__name__)

    if isinstance(node, ast.Subscript):
        base = node.value
        if not isinstance(base, ast.Name):
            raise ValueError(f"Unsupported generic base: {ast.dump(base)}")
        base_name = base.id

        if base_name in ("List", "list"):
            items_schema = _ast_node_to_openapi(node.slice, class_map)
            return {"type": "array", "items": items_schema}

        if base_name in ("Dict", "dict"):
            if isinstance(node.slice, ast.Tuple):
                elts = node.slice.elts
                if len(elts) != 2:
                    raise ValueError(f"Dict requires exactly 2 type args, got {len(elts)}")
                value_schema = _ast_node_to_openapi(elts[1], class_map)
                return {"type": "object", "additionalProperties": value_schema}
            value_schema = _ast_node_to_openapi(node.slice, class_map)
            return {"type": "object", "additionalProperties": value_schema}

        raise ValueError(f"Unsupported generic type: {base_name}")

    raise ValueError(f"Unsupported annotation node: {ast.dump(node)}")


def _is_dict_type(type_str: str) -> bool:
    """Check if a type string represents a Dict type (with or without parameters)."""
    _dict_names = ("dict", "Dict")
    return type_str in _dict_names or any(type_str.startswith(f"{n}[") for n in _dict_names)


def _contains_any(type_str: str) -> bool:
    """Check if a type string contains 'Any' as a standalone type token."""
    import re

    tokens = re.split(r"[\[\],\s]+", type_str)
    return "Any" in tokens


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _get_decorator_names(node: ast.FunctionDef) -> List[str]:
    """Return the simple names of all decorators on *node*."""
    names: List[str] = []
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name):
            names.append(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.append(dec.attr)
    return names


def _resolve_default(node: ast.expr) -> Any:
    """Turn an AST default-value node into a Python literal."""
    return ast.literal_eval(node)


def _annotation_to_str(node: ast.expr) -> str:
    """Return the source text of an annotation node, including generics."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        return type(node.value).__name__
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        base = _annotation_to_str(node.value)
        if isinstance(node.slice, ast.Tuple):
            args = ", ".join(_annotation_to_str(e) for e in node.slice.elts)
        else:
            args = _annotation_to_str(node.slice)
        return f"{base}[{args}]"
    return ast.dump(node)


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------


class ClassSchema:
    """Parsed representation of a class with typed fields (e.g. TypedDict)."""

    def __init__(self, name: str, fields: List[Tuple[str, ast.expr]]) -> None:
        self.name = name
        self.fields = fields  # [(field_name, type_annotation_node), ...]


class FunctionSchema:
    """Parsed representation of a single ``@entry_func`` function."""

    def __init__(
        self,
        name: str,
        docstring: Optional[str],
        params: List[Dict[str, Any]],
        return_type: Optional[str],
        return_type_node: Optional[ast.expr],
        prototype: str,
        input_schema: Optional[ClassSchema] = None,
        output_schema: Optional[ClassSchema] = None,
    ) -> None:
        self.name = name
        self.docstring = docstring
        self.params = params
        self.return_type = return_type
        self.return_type_node = return_type_node
        self.prototype = prototype
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.class_map: Dict[str, ClassSchema] = {}


def _find_class_in_tree(tree: ast.Module, class_name: str) -> ClassSchema:
    """Find a class definition by name and extract its annotated fields."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            fields: List[Tuple[str, ast.expr]] = []
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    fields.append((stmt.target.id, stmt.annotation))
            if not fields:
                raise ValueError(
                    f"Class '{class_name}' has no typed fields; " "cannot be used as a schema"
                )
            return ClassSchema(class_name, fields)
    raise ValueError(f"Class '{class_name}' not found in the source file")


def _is_parameterized_dict(type_str: str) -> bool:
    """Check if a type string is a parameterized Dict (not bare dict/Dict)."""
    return any(type_str.startswith(f"{n}[") for n in ("dict", "Dict"))


def _is_optional(node: ast.expr) -> bool:
    """Check if an annotation node is ``Optional[X]``."""
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Optional"
    )


def _unwrap_optional(node: ast.expr) -> ast.expr:
    """If *node* is ``Optional[X]``, return the inner ``X``."""
    if _is_optional(node):
        # _is_optional guarantees a Subscript; assert narrows it for the type checker.
        assert isinstance(node, ast.Subscript)
        return node.slice
    return node


def _build_class_openapi_schema(
    schema: ClassSchema,
    class_map: Optional[Dict[str, "ClassSchema"]] = None,
) -> Dict[str, Any]:
    """Build an OpenAPI schema from a ClassSchema's typed fields.

    Fields annotated with ``Optional[X]`` are included in ``properties`` but
    omitted from the ``required`` list.
    """
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for field_name, type_node in schema.fields:
        if _is_optional(type_node):
            properties[field_name] = _ast_node_to_openapi(_unwrap_optional(type_node), class_map)
        else:
            properties[field_name] = _ast_node_to_openapi(type_node, class_map)
            required.append(field_name)
    result: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = required
    return result


def extract_entry_functions(source: str) -> List[FunctionSchema]:
    """Parse *source* and return schemas for every ``@entry_func`` function.

    Raises ``ValueError`` when a decorated function has untyped parameters, the
    wrong signature, or uses a bare ``dict`` / ``Any`` without a schema class.
    """
    tree = ast.parse(source)
    results: List[FunctionSchema] = []

    # Build a map of all class definitions for nested TypedDict resolution.
    class_map: Dict[str, ClassSchema] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            fields: List[Tuple[str, ast.expr]] = []
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    fields.append((stmt.target.id, stmt.annotation))
            if fields:
                class_map[node.name] = ClassSchema(node.name, fields)

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if "entry_func" not in _get_decorator_names(node):
            continue

        args = node.args
        all_args = args.args
        defaults = args.defaults
        num_no_default = len(all_args) - len(defaults)

        params: List[Dict[str, Any]] = []
        proto_parts: List[str] = []

        for idx, arg in enumerate(all_args):
            if arg.annotation is None:
                raise ValueError(
                    f"Parameter '{arg.arg}' of function '{node.name}' "
                    "is missing a type annotation"
                )
            type_str = _annotation_to_str(arg.annotation)
            param: Dict[str, Any] = {
                "name": arg.arg,
                "type": type_str,
                "type_node": arg.annotation,
            }
            proto = f"{arg.arg}: {type_str}"

            default_idx = idx - num_no_default
            if default_idx >= 0:
                default_val = _resolve_default(defaults[default_idx])
                param["default"] = default_val
                proto += f" = {default_val!r}"

            params.append(param)
            proto_parts.append(proto)

        return_type: Optional[str] = None
        return_type_node: Optional[ast.expr] = None
        if node.returns is not None:
            return_type = _annotation_to_str(node.returns)
            return_type_node = node.returns

        if len(params) != 1:
            raise ValueError(
                f"Function '{node.name}' must have exactly one parameter "
                f"named 'request', got {len(params)} parameter(s)"
            )
        if params[0]["name"] != "request":
            raise ValueError(
                f"Function '{node.name}' must have a single parameter "
                f"named 'request', got '{params[0]['name']}'"
            )
        if not _is_dict_type(params[0]["type"]):
            raise ValueError(
                f"Parameter 'request' of function '{node.name}' must be "
                f"Dict type, got '{params[0]['type']}'"
            )
        if return_type is None:
            raise ValueError(f"Function '{node.name}' must have a Dict return type annotation")
        if not _is_dict_type(return_type):
            raise ValueError(f"Function '{node.name}' must return Dict type, got '{return_type}'")
        if _contains_any(params[0]["type"]):
            raise ValueError(
                f"Parameter 'request' of function '{node.name}' uses 'Any' "
                "which is not allowed; all types must be fully specified"
            )
        if _contains_any(return_type):
            raise ValueError(
                f"Return type of function '{node.name}' uses 'Any' "
                "which is not allowed; all types must be fully specified"
            )

        # --- detect @requestSchema / @responseSchema decorators -------------
        input_class_name: Optional[str] = None
        output_class_name: Optional[str] = None
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                if dec.func.id == "requestSchema" and dec.args:
                    if isinstance(dec.args[0], ast.Name):
                        input_class_name = dec.args[0].id
                elif dec.func.id == "responseSchema" and dec.args:
                    if isinstance(dec.args[0], ast.Name):
                        output_class_name = dec.args[0].id

        input_schema: Optional[ClassSchema] = None
        output_schema: Optional[ClassSchema] = None

        if input_class_name:
            input_schema = _find_class_in_tree(tree, input_class_name)
            for field_name, type_node_f in input_schema.fields:
                if _contains_any(_annotation_to_str(type_node_f)):
                    raise ValueError(
                        f"Field '{field_name}' in class '{input_class_name}' "
                        "uses 'Any' which is not allowed; all types must be "
                        "fully specified"
                    )

        if output_class_name:
            output_schema = _find_class_in_tree(tree, output_class_name)
            for field_name, type_node_f in output_schema.fields:
                if _contains_any(_annotation_to_str(type_node_f)):
                    raise ValueError(
                        f"Field '{field_name}' in class '{output_class_name}' "
                        "uses 'Any' which is not allowed; all types must be "
                        "fully specified"
                    )

        if not input_schema and not _is_parameterized_dict(params[0]["type"]):
            raise ValueError(
                f"Parameter 'request' of function '{node.name}' uses bare "
                "dict without @requestSchema; either use a parameterized "
                "Dict type (e.g. Dict[str, int]) or add @requestSchema"
            )
        if not output_schema and not _is_parameterized_dict(return_type):
            raise ValueError(
                f"Return type of function '{node.name}' uses bare dict "
                "without @responseSchema; either use a parameterized "
                "Dict type (e.g. Dict[str, int]) or add @responseSchema"
            )

        ret_str = f" -> {return_type}" if return_type else ""
        prototype = f"{node.name}({', '.join(proto_parts)}){ret_str}"

        fn_schema = FunctionSchema(
            name=node.name,
            docstring=ast.get_docstring(node),
            params=params,
            return_type=return_type,
            return_type_node=return_type_node,
            prototype=prototype,
            input_schema=input_schema,
            output_schema=output_schema,
        )
        fn_schema.class_map = class_map
        results.append(fn_schema)

    return results


# ---------------------------------------------------------------------------
# OpenAPI generation
# ---------------------------------------------------------------------------


def _title_from_name(name: str) -> str:
    """Convert a snake_case function name to a Title Case service name."""
    return name.replace("_", " ").title() + " Service"


def _build_schema_prototype(schema: ClassSchema) -> str:
    """Build a Python-style prototype string from a ClassSchema, e.g. ``dict(a: int)``."""
    parts = []
    for field_name, type_node in schema.fields:
        parts.append(f"{field_name}: {_annotation_to_str(type_node)}")
    return f"dict({', '.join(parts)})"


def _build_request_schema(
    params: List[Dict[str, Any]],
    input_schema: Optional[ClassSchema] = None,
    class_map: Optional[Dict[str, ClassSchema]] = None,
) -> Dict[str, Any]:
    """Build the request body schema from the single ``request`` Dict parameter."""
    if input_schema:
        return _build_class_openapi_schema(input_schema, class_map)
    p = params[0]
    type_source = p.get("type_node", p["type"])
    return python_type_to_openapi(type_source)


def _build_response_schema(
    schema: FunctionSchema,
    class_map: Optional[Dict[str, ClassSchema]] = None,
) -> Dict[str, Any]:
    """Build the response schema from the Dict return type."""
    if schema.output_schema:
        return _build_class_openapi_schema(schema.output_schema, class_map)
    type_source = schema.return_type_node or schema.return_type
    return python_type_to_openapi(type_source)


def _build_x_function(
    schema: FunctionSchema,
    namespace: str,
    package: str,
) -> Dict[str, Any]:
    """Build the ``x-sfdc`` code-extension object for an OpenAPI operation."""
    x_fn: Dict[str, Any] = {
        "feature": "BYOC",
        "language": "python",
        "namespace": namespace,
        "package": package,
        "name": f"{schema.name}Fn",
        "prototype": schema.prototype,
    }
    if schema.input_schema:
        x_fn["requestSchema"] = _build_schema_prototype(schema.input_schema)
    if schema.output_schema:
        x_fn["responseSchema"] = _build_schema_prototype(schema.output_schema)
    x_fn["description"] = f"Will perform {schema.name} operation"
    return x_fn


def generate_openapi(
    schemas: List[FunctionSchema],
    *,
    namespace: str = _DEFAULT_NAMESPACE,
    package: str = _DEFAULT_PACKAGE,
) -> Dict[str, Any]:
    """Build an OpenAPI 3.0.0 dict from a list of ``FunctionSchema`` objects."""
    if not schemas:
        raise ValueError("No @entry_func functions found in the input file")

    first = schemas[0]
    spec: Dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {
            "title": _title_from_name(first.name),
            "description": "API generated from Python function schema",
            "version": "1.0.0",
        },
        "paths": {},
    }

    for schema in schemas:
        summary = (schema.docstring or "").split("\n")[0].rstrip(".")
        path_op: Dict[str, Any] = {
            "summary": summary,
            "description": schema.docstring or "",
            "operationId": schema.name,
            "x-sfdc": {
                "code-extension": _build_x_function(schema, namespace, package),
            },
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": _build_request_schema(
                            schema.params, schema.input_schema, schema.class_map
                        ),
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "Successful response",
                    "content": {
                        "application/json": {
                            "schema": _build_response_schema(schema, schema.class_map),
                        }
                    },
                },
                "400": {"description": "Invalid input"},
            },
        }
        spec["paths"][f"/{schema.name}"] = {"post": path_op}

    return spec


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_schema(
    source: str,
    *,
    namespace: str = _DEFAULT_NAMESPACE,
    package: str = _DEFAULT_PACKAGE,
) -> Dict[str, Any]:
    """Return the OpenAPI 3.0.0 dict for the ``@entry_func`` functions in *source*.

    *source* is Python source code (a string), parsed via AST — never imported.
    """
    return generate_openapi(extract_entry_functions(source), namespace=namespace, package=package)


def generate_schema_yaml(
    source_path: str,
    *,
    namespace: str = _DEFAULT_NAMESPACE,
    package: str = _DEFAULT_PACKAGE,
) -> str:
    """Read the Python file at *source_path* and return its OpenAPI spec as YAML."""
    import yaml

    with open(source_path, "r") as f:
        source = f.read()
    spec = generate_schema(source, namespace=namespace, package=package)
    return cast(str, yaml.dump(spec, default_flow_style=False, sort_keys=False))


# ---------------------------------------------------------------------------
# Config file support
# ---------------------------------------------------------------------------


def load_config(config_path: str) -> Dict[str, str]:
    """Load namespace/package from a YAML or JSON config file.

    The file may contain any keys; only ``namespace`` and ``package`` are used.
    """
    with open(config_path, "r") as f:
        raw = f.read()

    if config_path.endswith(".json"):
        import json

        data = json.loads(raw)
    else:
        import yaml

        data = yaml.safe_load(raw)

    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping, got {type(data).__name__}")
    return {k: v for k, v in data.items() if k in ("namespace", "package")}


def resolve_config(
    *,
    cli_namespace: Optional[str],
    cli_package: Optional[str],
    config_path: Optional[str],
) -> Tuple[str, str]:
    """Determine final namespace and package values.

    Precedence (highest → lowest): CLI flags, config file, built-in defaults.
    """
    file_ns: Optional[str] = None
    file_pkg: Optional[str] = None

    if config_path is not None:
        cfg = load_config(config_path)
        file_ns = cfg.get("namespace")
        file_pkg = cfg.get("package")

    namespace = cli_namespace or file_ns or _DEFAULT_NAMESPACE
    package = cli_package or file_pkg or _DEFAULT_PACKAGE
    return namespace, package


# ---------------------------------------------------------------------------
# CLI (python -m agentforce_byoc.schema_utils.generator ...)
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate OpenAPI spec from @entry_func functions."
    )
    parser.add_argument("input", help="Path to the Python source file")
    parser.add_argument("-o", "--output", default=None, help="Output YAML file (default: stdout)")
    parser.add_argument(
        "--namespace", default=None, help="Function namespace (overrides config file)"
    )
    parser.add_argument("--package", default=None, help="Function package (overrides config file)")
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="Path to a YAML or JSON config file with namespace/package",
    )

    args = parser.parse_args(argv)

    namespace, package = resolve_config(
        cli_namespace=args.namespace,
        cli_package=args.package,
        config_path=args.config,
    )

    yaml_str = generate_schema_yaml(args.input, namespace=namespace, package=package)

    if args.output:
        with open(args.output, "w") as f:
            f.write(yaml_str)
    else:
        sys.stdout.write(yaml_str)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
