# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the generated ``main.py`` scaffold (main.py.template).

The template's ``main()`` binds the invoke payload from the module global
``byoc_input`` using an *unbound* sentinel, and emits the function's return as a
``result: <json>`` line on stdout. Those two behaviors are the scaffold's
headline feature, so they get direct coverage here:

- an *unbound* ``byoc_input`` (a local ``python main.py`` run) falls back to the
  sample request built from ``_DEFAULT_PROMPT``;
- a *bound* ``byoc_input`` is passed through verbatim — even ``None`` — and is
  never silently replaced by the sample; and
- ``main()`` prints a ``result: <json>`` line.

The bound-``None`` case is the regression guard the inline comment warns about:
a ``byoc_input is None`` check (or ``byoc_input or {...}``) would swap ``None``
for the sample, which these tests would catch.
"""

from pathlib import Path

from agentforce_byoc.cli import commands

# Distinct sentinel so a spy that is never called is distinguishable from one
# called with ``None``.
_UNSET = object()


def _render_and_load(tmp_path):
    """Render main.py.template into ``tmp_path`` and exec it into a fresh namespace.

    Returns the rendered module's namespace dict (its globals). ``__name__`` is
    set to a non-``"__main__"`` value so the ``if __name__ == "__main__"`` guard
    does not auto-invoke ``main()``.
    """
    template_path = (
        Path(commands.__file__).parent.parent / "templates" / "agent" / "main.py.template"
    )
    rendered = tmp_path / "main.py"
    commands.render_template(
        template_path,
        rendered,
        {"project_name": "my-agent", "agent_class_name": "MyAgent"},
    )
    namespace = {"__name__": "rendered_main_under_test"}
    exec(compile(rendered.read_text(), str(rendered), "exec"), namespace)
    return namespace


def _install_spy(namespace):
    """Replace the module's ``function`` with a spy recording its argument.

    Returns a dict updated on each call: ``called`` and the received ``request``.
    """
    captured = {"called": False, "request": _UNSET}

    def spy(request):
        captured["called"] = True
        captured["request"] = request
        return {"result": "spy", "status": "success"}

    namespace["function"] = spy
    return captured


def test_main_unbound_falls_back_to_sample(tmp_path):
    """With no ``byoc_input`` bound (local run), ``main`` uses the sample request."""
    namespace = _render_and_load(tmp_path)
    captured = _install_spy(namespace)
    # A local ``python main.py`` never binds the runtime global.
    assert "byoc_input" not in namespace

    namespace["main"]()

    assert captured["called"] is True
    # The unbound global selects the local sample, built from _DEFAULT_PROMPT.
    assert captured["request"] == {"text": namespace["_DEFAULT_PROMPT"]}


def test_main_bound_none_is_respected(tmp_path):
    """A runtime-bound ``byoc_input`` of ``None`` is passed through, not replaced.

    Regression guard: a ``byoc_input is None`` check (or ``... or {...}``) would
    substitute the sample here. The sentinel must pass ``None`` through unchanged.

    Scope is deliberately limited to ``main()``'s dispatch decision. The spy
    isolates that decision from the function body: with the real ``function`` a
    ``None`` request raises ``AttributeError`` (``list(None.keys())``) before any
    result line, so this test asserts only *what value main() dispatches*, not a
    result line. End-to-end result-line coverage lives in
    ``test_main_bound_empty_dict_runs_real_function_and_emits_result``.
    """
    namespace = _render_and_load(tmp_path)
    captured = _install_spy(namespace)
    namespace["byoc_input"] = None  # runtime bound the invoke input to null

    namespace["main"]()

    assert captured["called"] is True
    assert captured["request"] is None


def test_main_bound_empty_dict_runs_real_function_and_emits_result(tmp_path, capsys):
    """A bound empty ``{}`` is respected and the real function emits a result line.

    Uses the real (un-spied) ``function``: an empty request has no ``text``, so
    it returns the input-error response, and ``main()`` prints it as ``result:``.
    """
    namespace = _render_and_load(tmp_path)  # real `function`, no spy
    namespace["byoc_input"] = {}

    namespace["main"]()

    out = capsys.readouterr().out
    # The empty dict is respected as-is, not swapped for the sample prompt.
    assert "Request: {}" in out
    assert namespace["_DEFAULT_PROMPT"] not in out
    # The real function's empty-text error path still emits a result line.
    assert 'result: {"result": "", "status": "error"}' in out
