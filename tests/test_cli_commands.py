# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``agentforce`` CLI commands (agentforce_byoc.cli.commands).

Exercises every command (init, run, validate, zip, package, deploy,
deploy-status, generate-schema) and the module helpers through click's
``CliRunner``, mocking the subprocess / network boundaries so nothing real is
spawned or uploaded.

The CLI reports progress through the stdlib ``logging`` module (not
``click.echo``), so those messages do NOT land in ``result.output``; tests
assert on ``caplog.text`` instead. Only click-native output (``click.echo`` in
``generate-schema`` and click's own ``Aborted!`` / ``BadParameter`` messages)
is asserted via ``result.output``.
"""

import json
import logging
import subprocess
import tarfile
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from agentforce_byoc.cli import commands
from agentforce_byoc.cli.main import cli

VALID_TENANT = "core/instance-core4/00Dxx0000000000"
VALID_USER_ID = "005xx000001234567"
VALID_APP_CONTEXT = "EinsteinGPT"

_IDENTITY_VARS = (
    "ORG_JWT_TOKEN",
    "SFDC_CORE_TENANT_ID",
    "SFDC_USER_ID",
    "SFDC_APP_CONTEXT",
    "BYOC_PROXY_URL",
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def capture_logs(caplog):
    """Capture the CLI's stdlib-logging output at INFO so tests can assert it."""
    caplog.set_level(logging.INFO, logger="agentforce_byoc.cli.commands")
    return caplog


@pytest.fixture(autouse=True)
def clear_identity_env(monkeypatch):
    """Ensure identity env vars never leak between tests."""
    for var in _IDENTITY_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def with_identity_env(monkeypatch):
    """Set the four identity env vars every real call requires."""
    monkeypatch.setenv("ORG_JWT_TOKEN", "test-jwt")
    monkeypatch.setenv("SFDC_CORE_TENANT_ID", VALID_TENANT)
    monkeypatch.setenv("SFDC_USER_ID", VALID_USER_ID)
    monkeypatch.setenv("SFDC_APP_CONTEXT", VALID_APP_CONTEXT)


def _make_project_files(root: Path):
    """Create the minimal set of files validate/zip expect."""
    (root / "main.py").write_text("def function(request):\n    return {}\n")
    (root / "entry_func.py").write_text("# entry\n")
    (root / "schema.py").write_text("# schema\n")
    (root / "pyproject.toml").write_text("[tool.poetry]\nname='x'\n")
    (root / "poetry.lock").write_text("# lock\n")
    (root / "Dockerfile").write_text("FROM python:3.11\n")
    (root / "config.json").write_text(json.dumps({"name": "myfunc", "version": "0.1.0"}))


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_creates_project(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "my-agent"])
        assert result.exit_code == 0, result.output
        project = Path("my-agent")
        assert (project / "main.py").exists()
        assert (project / "config.json").exists()
        # SDK is vendored into the project.
        assert (project / "agentforce_byoc" / "__init__.py").exists()


def test_init_rejects_invalid_name(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "BadName"])
        assert result.exit_code != 0
        # click.BadParameter renders to result.output.
        assert "Invalid project name" in result.output


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_passes(runner, caplog):
    with runner.isolated_filesystem():
        _make_project_files(Path("."))
        result = runner.invoke(cli, ["validate", "."])
        assert result.exit_code == 0, result.output
        assert "Validation passed" in caplog.text


def test_validate_missing_pyproject(runner, caplog):
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["validate", "."])
        assert result.exit_code != 0
        assert "pyproject.toml not found" in caplog.text


def test_validate_missing_lock(runner, caplog):
    with runner.isolated_filesystem():
        Path("pyproject.toml").write_text("[tool.poetry]\n")
        result = runner.invoke(cli, ["validate", "."])
        assert result.exit_code != 0
        assert "poetry.lock not found" in caplog.text


def test_validate_missing_source_file(runner, caplog):
    with runner.isolated_filesystem():
        Path("pyproject.toml").write_text("[tool.poetry]\n")
        Path("poetry.lock").write_text("# lock\n")
        result = runner.invoke(cli, ["validate", "."])
        assert result.exit_code != 0
        assert "main.py not found" in caplog.text


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_requires_env(runner, caplog):
    with runner.isolated_filesystem():
        Path("main.py").write_text("print('hi')\n")
        result = runner.invoke(cli, ["run", "main.py"])
        assert result.exit_code != 0
        assert "ORG_JWT_TOKEN is not set" in caplog.text


def test_run_executes_subprocess(runner, with_identity_env, monkeypatch):
    calls = {}

    def fake_run(cmd, check, env):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(commands.subprocess, "run", fake_run)
    with runner.isolated_filesystem():
        Path("main.py").write_text("print('hi')\n")
        result = runner.invoke(cli, ["run", "main.py"])
        assert result.exit_code == 0, result.output
        assert calls["cmd"] == ["python", "main.py"]


def test_run_subprocess_failure_aborts(runner, with_identity_env, monkeypatch, caplog):
    def fake_run(cmd, check, env):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(commands.subprocess, "run", fake_run)
    with runner.isolated_filesystem():
        Path("main.py").write_text("boom\n")
        result = runner.invoke(cli, ["run", "main.py"])
        assert result.exit_code != 0
        assert "Agent execution failed" in caplog.text


# ---------------------------------------------------------------------------
# helpers: require_env_var / _resolve_base_url / render_template / vendor
# ---------------------------------------------------------------------------


def test_require_env_var_returns_value(monkeypatch):
    monkeypatch.setenv("SOME_VAR", "value")
    assert commands.require_env_var("SOME_VAR", "label") == "value"


def test_require_env_var_aborts_when_unset(monkeypatch):
    monkeypatch.delenv("SOME_VAR", raising=False)
    with pytest.raises(click.Abort):
        commands.require_env_var("SOME_VAR", "label", "<hint>")


def test_resolve_base_url_ok():
    assert commands._resolve_base_url(VALID_TENANT) == "https://api.salesforce.com"


def test_resolve_base_url_bad_tenant_aborts():
    with pytest.raises(click.Abort):
        commands._resolve_base_url("garbage")


def test_render_template(tmp_path):
    template = tmp_path / "t.template"
    template.write_text("Hello {{project_name}} / {{agent_class_name}}")
    out = tmp_path / "out.txt"
    commands.render_template(template, out, {"project_name": "foo", "agent_class_name": "Foo"})
    assert out.read_text() == "Hello foo / Foo"


def test_vendor_sdk_into_project(tmp_path):
    count = commands.vendor_sdk_into_project(tmp_path)
    assert count > 0
    assert (tmp_path / "agentforce_byoc" / "__init__.py").exists()
    # cli/ and templates/ are intentionally excluded from the runtime vendor set.
    assert not (tmp_path / "agentforce_byoc" / "cli").exists()
    assert not (tmp_path / "agentforce_byoc" / "templates").exists()


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------


def test_deploy_requires_env(runner, caplog):
    with runner.isolated_filesystem():
        Path("pkg.tar.gz").write_bytes(b"data")
        result = runner.invoke(
            cli, ["deploy", "--package-name", "p", "--package-file", "pkg.tar.gz"]
        )
        assert result.exit_code != 0
        assert "SFDC_CORE_TENANT_ID is not set" in caplog.text


def test_deploy_happy_path(runner, with_identity_env, monkeypatch, caplog):
    captured = {}

    def fake_presign(**kwargs):
        captured.update(kwargs)
        return {"uploadUrl": "https://s3/upload", "s3Key": "key/123"}

    def fake_upload(url, path):
        captured["upload"] = (url, str(path))

    monkeypatch.setattr("agentforce_byoc.deploy_client.request_presigned_upload", fake_presign)
    monkeypatch.setattr("agentforce_byoc.deploy_client.upload_package", fake_upload)

    with runner.isolated_filesystem():
        Path("pkg.tar.gz").write_bytes(b"data")
        result = runner.invoke(
            cli,
            [
                "deploy",
                "--package-name",
                "mypkg",
                "--package-file",
                "pkg.tar.gz",
                "--version",
                "2.0",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "deployed successfully" in caplog.text
        assert captured["package_name"] == "mypkg"
        assert captured["version"] == "2.0"
        assert captured["tenant_id"] == VALID_TENANT
        assert captured["base_url"] == "https://api.salesforce.com"
        assert captured["upload"][0] == "https://s3/upload"


def test_deploy_register_failure_aborts(runner, with_identity_env, monkeypatch, caplog):
    def fake_presign(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("agentforce_byoc.deploy_client.request_presigned_upload", fake_presign)
    with runner.isolated_filesystem():
        Path("pkg.tar.gz").write_bytes(b"data")
        result = runner.invoke(
            cli, ["deploy", "--package-name", "p", "--package-file", "pkg.tar.gz"]
        )
        assert result.exit_code != 0
        assert "Failed to register" in caplog.text


def test_deploy_missing_upload_url_aborts(runner, with_identity_env, monkeypatch, caplog):
    monkeypatch.setattr(
        "agentforce_byoc.deploy_client.request_presigned_upload",
        lambda **kwargs: {"s3Key": "key"},  # no uploadUrl
    )
    with runner.isolated_filesystem():
        Path("pkg.tar.gz").write_bytes(b"data")
        result = runner.invoke(
            cli, ["deploy", "--package-name", "p", "--package-file", "pkg.tar.gz"]
        )
        assert result.exit_code != 0
        assert "missing 'uploadUrl'" in caplog.text


def test_deploy_upload_failure_aborts(runner, with_identity_env, monkeypatch, caplog):
    monkeypatch.setattr(
        "agentforce_byoc.deploy_client.request_presigned_upload",
        lambda **kwargs: {"uploadUrl": "https://s3/upload", "s3Key": "key"},
    )

    def fake_upload(url, path):
        raise RuntimeError("upload failed")

    monkeypatch.setattr("agentforce_byoc.deploy_client.upload_package", fake_upload)
    with runner.isolated_filesystem():
        Path("pkg.tar.gz").write_bytes(b"data")
        result = runner.invoke(
            cli, ["deploy", "--package-name", "p", "--package-file", "pkg.tar.gz"]
        )
        assert result.exit_code != 0
        assert "upload failed" in caplog.text


# ---------------------------------------------------------------------------
# deploy-status
# ---------------------------------------------------------------------------


def test_deploy_status_requires_env(runner, caplog):
    result = runner.invoke(cli, ["deploy-status", "--package-name", "p"])
    assert result.exit_code != 0
    assert "SFDC_CORE_TENANT_ID is not set" in caplog.text


def test_deploy_status_happy_path(runner, with_identity_env, monkeypatch, caplog):
    def fake_status(**kwargs):
        return {
            "s3Key": "key/1",
            "registrationStatus": "registered",
            "uploadStatus": "uploaded",
            "uploadTime": "2026-01-01",
        }

    monkeypatch.setattr("agentforce_byoc.deploy_client.get_upload_status", fake_status)
    result = runner.invoke(cli, ["deploy-status", "--package-name", "mypkg", "--version", "3.0"])
    assert result.exit_code == 0, result.output
    assert "registered" in caplog.text
    assert "uploaded" in caplog.text


def test_deploy_status_failure_aborts(runner, with_identity_env, monkeypatch, caplog):
    def fake_status(**kwargs):
        raise RuntimeError("status boom")

    monkeypatch.setattr("agentforce_byoc.deploy_client.get_upload_status", fake_status)
    result = runner.invoke(cli, ["deploy-status", "--package-name", "p"])
    assert result.exit_code != 0
    assert "Failed to poll" in caplog.text


# ---------------------------------------------------------------------------
# generate-schema
# ---------------------------------------------------------------------------


def test_generate_schema_to_stdout(runner, monkeypatch):
    monkeypatch.setattr(
        "agentforce_byoc.schema_utils.generator.resolve_config",
        lambda cli_namespace, cli_package, config_path: ("ns", "pkg"),
    )
    monkeypatch.setattr(
        "agentforce_byoc.schema_utils.generator.generate_schema_yaml",
        lambda input, namespace, package: "openapi: 3.0.0\n",
    )
    with runner.isolated_filesystem():
        Path("main.py").write_text("# code\n")
        result = runner.invoke(cli, ["generate-schema", "main.py"])
        assert result.exit_code == 0, result.output
        # generate-schema writes to stdout via click.echo -> result.output.
        assert "openapi: 3.0.0" in result.output


def test_generate_schema_to_file(runner, monkeypatch, caplog):
    monkeypatch.setattr(
        "agentforce_byoc.schema_utils.generator.resolve_config",
        lambda cli_namespace, cli_package, config_path: ("ns", "pkg"),
    )
    monkeypatch.setattr(
        "agentforce_byoc.schema_utils.generator.generate_schema_yaml",
        lambda input, namespace, package: "openapi: 3.0.0\n",
    )
    with runner.isolated_filesystem():
        Path("main.py").write_text("# code\n")
        result = runner.invoke(cli, ["generate-schema", "main.py", "-o", "out.yaml"])
        assert result.exit_code == 0, result.output
        assert Path("out.yaml").read_text() == "openapi: 3.0.0\n"
        assert "Wrote OpenAPI spec" in caplog.text


def test_generate_schema_error_aborts(runner, monkeypatch, caplog):
    monkeypatch.setattr(
        "agentforce_byoc.schema_utils.generator.resolve_config",
        lambda cli_namespace, cli_package, config_path: ("ns", "pkg"),
    )

    def boom(input, namespace, package):
        raise ValueError("bad schema")

    monkeypatch.setattr("agentforce_byoc.schema_utils.generator.generate_schema_yaml", boom)
    with runner.isolated_filesystem():
        Path("main.py").write_text("# code\n")
        result = runner.invoke(cli, ["generate-schema", "main.py"])
        assert result.exit_code != 0
        assert "Failed to generate schema" in caplog.text


# ---------------------------------------------------------------------------
# zip
# ---------------------------------------------------------------------------


def _patch_zip_boundaries(monkeypatch):
    """Stub poetry export + pip download so zip touches no external tools."""

    def fake_export(project_path, requirements_path):
        Path(requirements_path).write_text("click==8.1.7\n")

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        # pip download: create nothing in the target dir; return success.
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(commands, "export_requirements", fake_export)
    monkeypatch.setattr(commands.subprocess, "run", fake_run)


def test_zip_happy_path(runner, monkeypatch):
    _patch_zip_boundaries(monkeypatch)
    with runner.isolated_filesystem():
        _make_project_files(Path("."))
        result = runner.invoke(cli, ["zip", "."])
        assert result.exit_code == 0, result.output
        archive = Path("myfunc-0.1.0.tar.gz")
        assert archive.exists()
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
        assert "main.py" in names
        assert "config.json" in names
        # temporary dependencies dir is cleaned up
        assert not Path("dependencies").exists()


def test_zip_custom_output(runner, monkeypatch):
    _patch_zip_boundaries(monkeypatch)
    with runner.isolated_filesystem():
        _make_project_files(Path("."))
        result = runner.invoke(cli, ["zip", ".", "--output", "custom.tar.gz"])
        assert result.exit_code == 0, result.output
        assert Path("custom.tar.gz").exists()


def test_zip_missing_config_aborts(runner, caplog):
    with runner.isolated_filesystem():
        Path("main.py").write_text("x=1\n")
        result = runner.invoke(cli, ["zip", "."])
        assert result.exit_code != 0
        assert "config.json not found" in caplog.text


def test_zip_invalid_config_aborts(runner, monkeypatch, caplog):
    _patch_zip_boundaries(monkeypatch)
    with runner.isolated_filesystem():
        _make_project_files(Path("."))
        Path("config.json").write_text("{not json")
        result = runner.invoke(cli, ["zip", "."])
        assert result.exit_code != 0
        assert "Invalid config.json" in caplog.text


# ---------------------------------------------------------------------------
# package (validate -> run -> zip)
# ---------------------------------------------------------------------------


def test_package_pipeline(runner, with_identity_env, monkeypatch, caplog):
    def fake_export(project_path, requirements_path):
        Path(requirements_path).write_text("click==8.1.7\n")

    def fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(commands, "export_requirements", fake_export)
    monkeypatch.setattr(commands.subprocess, "run", fake_run)

    with runner.isolated_filesystem():
        _make_project_files(Path("."))
        result = runner.invoke(cli, ["package", "."])
        assert result.exit_code == 0, result.output
        assert "Package pipeline complete" in caplog.text


# ---------------------------------------------------------------------------
# export_requirements
# ---------------------------------------------------------------------------


def test_export_requirements_success(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(commands.subprocess, "run", fake_run)
    commands.export_requirements(tmp_path, tmp_path / "requirements.txt")
    assert calls[0][:2] == ["poetry", "export"]


def test_export_requirements_installs_plugin_on_missing_command(tmp_path, monkeypatch):
    """Poetry 2.x path: export missing -> install plugin -> retry succeeds."""
    seq = []

    def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False):
        seq.append(cmd)
        if cmd[:2] == ["poetry", "export"] and len(seq) == 1:
            raise subprocess.CalledProcessError(
                1, cmd, output="", stderr="command export does not exist"
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(commands.subprocess, "run", fake_run)
    commands.export_requirements(tmp_path, tmp_path / "requirements.txt")
    # install plugin call happened between the failed and retried export
    assert ["poetry", "self", "add", "poetry-plugin-export"] in seq


def test_export_requirements_hard_failure_aborts(tmp_path, monkeypatch):
    def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False):
        raise subprocess.CalledProcessError(1, cmd, output="", stderr="lockfile missing")

    monkeypatch.setattr(commands.subprocess, "run", fake_run)
    with pytest.raises(click.Abort):
        commands.export_requirements(tmp_path, tmp_path / "requirements.txt")
