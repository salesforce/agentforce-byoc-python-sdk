# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0

"""CLI commands for Agentforce BYOC SDK."""

import os
import re
import subprocess
from pathlib import Path

import click

from agentforce_byoc.cli.main import cli
from agentforce_byoc.gateway.relay_client import resolve_sfap_base_url
from agentforce_byoc.logging import get_logger

logger = get_logger(__name__)


@cli.command()
@click.argument("directory", default=".")
def init(directory: str):
    """
    Initialize a new agent project with Poetry.

    Creates a new directory with:
    - main.py (template agent)
    - entry_func.py (entry point decorator)
    - schema.py (request/response schema decorators)
    - config.json (function metadata)
    - Dockerfile (container definition)
    - pyproject.toml (Poetry config)
    - README.md (documentation)
    - .python-version (Python 3.11)

    Example:
        agentforce init my-agent
        cd my-agent
        poetry install
        agentforce run main.py
    """
    project_path = Path(directory)
    project_name = project_path.name

    # Validate project name
    if not re.match(r"^[a-z][a-z0-9_-]*$", project_name):
        raise click.BadParameter(
            f"Invalid project name: {project_name}. "
            "Must start with lowercase letter and contain only lowercase letters, "
            "numbers, hyphens, and underscores."
        )

    # Create directory
    project_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Creating project: {project_name}")

    # Generate agent class name (e.g., my-agent -> MyAgent)
    agent_class_name = "".join(
        word.capitalize() for word in project_name.replace("-", "_").split("_")
    )

    # Template variables
    template_vars = {
        "project_name": project_name,
        "agent_class_name": agent_class_name,
    }

    # Copy and render templates
    templates_dir = Path(__file__).parent.parent / "templates" / "agent"

    files_created = []
    for template_file in templates_dir.glob("*.template"):
        output_filename = template_file.stem
        # Handle hidden files (e.g., .gitignore.template -> .gitignore)
        if template_file.stem.startswith("."):
            output_filename = template_file.stem
        output_file = project_path / output_filename
        render_template(template_file, output_file, template_vars)
        files_created.append(output_filename)

    # Vendor the SDK runtime package into the project so `main.py` can import
    # agentforce_byoc and `agentforce zip` can ship it. TODO(WI): remove once
    # the SDK is on PyPI (see vendor_sdk_into_project).
    sdk_file_count = vendor_sdk_into_project(project_path)
    if sdk_file_count:
        files_created.append(f"agentforce_byoc/ ({sdk_file_count} files)")

    logger.info(f"\n✅ Project {project_name} created successfully!")
    logger.info("\nFiles created:")
    for filename in sorted(files_created):
        logger.info(f"  ✓ {filename}")

    logger.info("\n📦 Project structure:")
    logger.info(f"  {project_name}/")
    logger.info("  ├── main.py               # Your function implementation")
    logger.info("  ├── entry_func.py         # Entry point decorator")
    logger.info("  ├── schema.py             # Request/response schema decorators")
    logger.info("  ├── agentforce_byoc/      # Vendored SDK (until published to PyPI)")
    logger.info("  ├── config.json           # Function metadata")
    logger.info("  ├── Dockerfile            # Container definition")
    logger.info("  ├── pyproject.toml        # Dependencies (Poetry)")
    logger.info("  ├── .python-version       # Python 3.11")
    logger.info("  ├── .gitignore            # Git ignore patterns")
    logger.info("  ├── .dockerignore         # Docker ignore patterns")
    logger.info("  ├── Makefile             # Development tasks")
    logger.info("  └── README.md            # Documentation")

    logger.info("\n🚀 Next steps:")
    logger.info(f"  1. cd {directory}")
    logger.info("  2. poetry install")
    logger.info("  3. # Implement your function logic in main.py")
    logger.info(
        "  4. export ORG_JWT_TOKEN=<jwt> && export SFDC_CORE_TENANT_ID=core/<inst>-<fd>/<org>"
        " && export SFDC_USER_ID=<user-id> && export SFDC_APP_CONTEXT=<app-context>"
    )
    logger.info("  5. agentforce run main.py                # Test locally")
    logger.info("  6. agentforce zip --package-dir .        # Package for deployment")
    logger.info("  7. agentforce deploy --package-name <name> --package-file <archive>.tar.gz")

    logger.info("\n💡 Tips:")
    logger.info("  • Edit main.py to implement your function")
    logger.info(
        "  • Set ORG_JWT_TOKEN + SFDC_CORE_TENANT_ID + SFDC_USER_ID + SFDC_APP_CONTEXT"
        " env vars before run/deploy"
    )
    logger.info("  • Add dependencies with: poetry add <package>")
    logger.info("  • Check Makefile for useful commands")


@cli.command()
@click.argument("entrypoint", type=click.Path(exists=True), default="main.py")
def run(entrypoint: str):
    """
    Run agent locally against the Agentforce BYOC runtime.

    Configuration is taken from environment variables (no CLI flags):
        - ORG_JWT_TOKEN: org JWT for authentication
        - SFDC_CORE_TENANT_ID: core tenant id (core/<instance>-<fd>/<org-id>)
        - SFDC_USER_ID: caller's user id
        - SFDC_APP_CONTEXT: app context (relay requires the x-sfdc-app-context header)
    If any is unset, the command aborts with an export instruction.

    Examples:
        export ORG_JWT_TOKEN=<org-jwt>
        export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
        export SFDC_USER_ID=<user-id>
        export SFDC_APP_CONTEXT=<app-context>
        agentforce run main.py
    """
    logger.info("🚀 Running with Agentforce BYOC runtime")
    # The relay client reads ORG_JWT_TOKEN, SFDC_CORE_TENANT_ID, SFDC_USER_ID,
    # and SFDC_APP_CONTEXT from the environment (the runtime injects these in
    # the managed sandbox). Require them locally so a missing value aborts with
    # an actionable export hint instead of failing mid-relay, then pass them to
    # the agent subprocess.
    require_env_var("ORG_JWT_TOKEN", "org JWT", "<jwt>")
    require_env_var("SFDC_CORE_TENANT_ID", "core tenant id", "core/<instance>-<fd>/<org-id>")
    require_env_var("SFDC_USER_ID", "user id", "<user-id>")
    require_env_var("SFDC_APP_CONTEXT", "app context", "<app-context>")

    # Child process inherits the environment.
    env = os.environ.copy()

    # Execute the agent
    logger.info(f"▶️  Executing: {entrypoint}")
    logger.info("")
    try:
        subprocess.run(["python", entrypoint], check=True, env=env)
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Agent execution failed: {e}")
        raise click.Abort()


@cli.command()
@click.argument("path", type=click.Path(exists=True), default=".")
def validate(path: str):
    """
    Validate agent package before deployment.

    Checks:
    - pyproject.toml exists and is valid
    - poetry.lock exists
    - main.py exists
    - entry_func.py exists
    - schema.py exists

    Example:
        agentforce validate .
    """
    project_path = Path(path)
    logger.info(f"Validating project: {project_path}")

    # Check pyproject.toml
    pyproject_path = project_path / "pyproject.toml"
    if not pyproject_path.exists():
        logger.error("pyproject.toml not found")
        raise click.Abort()
    logger.info("✓ pyproject.toml found")

    # Check poetry.lock
    lock_path = project_path / "poetry.lock"
    if not lock_path.exists():
        logger.error("poetry.lock not found. Run 'poetry install' first.")
        raise click.Abort()
    logger.info("✓ poetry.lock found")

    # Check required source files
    required_files = ["main.py", "entry_func.py", "schema.py"]
    for filename in required_files:
        file_path = project_path / filename
        if not file_path.exists():
            logger.error(f"{filename} not found")
            raise click.Abort()
        logger.info(f"✓ {filename} found")

    logger.info("\n✅ Validation passed!")


@cli.command()
@click.argument("package_dir", type=click.Path(exists=True), default=".")
@click.option(
    "--output",
    type=click.Path(),
    help="Output archive path (default: <name>-<version>.tar.gz)",
)
def zip(package_dir: str, output: str):
    """
    Create a gzip-compressed tar archive of the function package for deployment.

    The Agentforce BYOC upload contract expects a gzip archive
    (``application/gzip``), so this produces a ``.tar.gz`` ready for
    ``agentforce deploy``. Contains:
    - main.py (function code)
    - entry_func.py (entry point decorator)
    - schema.py (request/response schema decorators)
    - config.json (metadata)
    - Dockerfile (container definition)
    - pyproject.toml (dependencies)
    - poetry.lock (locked versions)
    - requirements.txt (exported from poetry)

    Example:
        agentforce zip --package-dir .
        agentforce zip --package-dir . --output my-function.tar.gz
    """
    import json
    import tarfile

    project_path = Path(package_dir).resolve()
    logger.info(f"📦 Packaging function: {project_path.name}")

    # Validate required files
    config_path = project_path / "config.json"
    if not config_path.exists():
        logger.error("❌ config.json not found. Is this an Agentforce BYOC function?")
        logger.info("Run 'agentforce init' to create a new function.")
        raise click.Abort()

    agent_path = project_path / "main.py"
    if not agent_path.exists():
        logger.error("❌ main.py not found")
        raise click.Abort()

    dockerfile_path = project_path / "Dockerfile"
    if not dockerfile_path.exists():
        logger.error("❌ Dockerfile not found")
        raise click.Abort()

    pyproject_path = project_path / "pyproject.toml"
    if not pyproject_path.exists():
        logger.error("❌ pyproject.toml not found")
        raise click.Abort()

    lock_path = project_path / "poetry.lock"
    if not lock_path.exists():
        logger.error("❌ poetry.lock not found. Run 'poetry install' first.")
        raise click.Abort()

    # Read config.json
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        function_name = config.get("name", project_path.name)
        function_version = config.get("version", "0.1.0")
        logger.info(f"Function: {function_name} v{function_version}")
    except json.JSONDecodeError as e:
        logger.error(f"❌ Invalid config.json: {e}")
        raise click.Abort()

    # Export requirements.txt from poetry
    requirements_path = project_path / "requirements.txt"
    logger.info("📝 Exporting dependencies...")
    export_requirements(project_path, requirements_path)

    # Download dependencies for bundling
    dependencies_dir = project_path / "dependencies"
    logger.info("📥 Downloading dependencies for bundling...")
    try:
        # Create temporary directory for downloads
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Download all dependencies using pip
            subprocess.run(
                [
                    "pip",
                    "download",
                    "-r",
                    str(requirements_path),
                    "-d",
                    str(temp_path),
                    "--no-deps",  # Don't download transitive dependencies (already in requirements.txt)
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            # Filter out packages to exclude
            exclude_packages = [
                "agentforce-byoc",
                "agentforce_byoc",
            ]

            # Create dependencies directory
            if dependencies_dir.exists():
                shutil.rmtree(dependencies_dir)
            dependencies_dir.mkdir()

            # Copy filtered packages
            package_count = 0
            for file in temp_path.iterdir():
                if file.is_file():
                    # Check if this package should be excluded
                    filename_lower = file.name.lower()
                    should_exclude = any(
                        pkg.lower().replace("-", "_") in filename_lower.replace("-", "_")
                        for pkg in exclude_packages
                    )

                    if not should_exclude:
                        shutil.copy2(file, dependencies_dir / file.name)
                        package_count += 1
                        logger.info(f"  ✓ Bundled: {file.name}")

            logger.info(f"✓ Downloaded and bundled {package_count} dependencies")

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to download dependencies: {e.stderr}")
        logger.info("Make sure pip is available and requirements.txt is valid.")
        raise click.Abort()
    except Exception as e:
        logger.error(f"❌ Error bundling dependencies: {e}")
        raise click.Abort()

    # Determine output filename
    if output is None:
        output = f"{function_name}-{function_version}.tar.gz"
    output_path = Path(output).resolve()

    # Files to include in the archive
    files_to_zip = [
        "main.py",
        "entry_func.py",
        "schema.py",
        "config.json",
        "Dockerfile",
        "pyproject.toml",
        "requirements.txt",
        ".python-version",
    ]

    # Optional files
    optional_files = [
        "poetry.lock",
        ".dockerignore",
        "README.md",
    ]

    logger.info(f"🗜️  Creating archive: {output_path.name}")

    # Create gzip-compressed tar archive
    try:
        with tarfile.open(output_path, "w:gz") as tar:
            # Add required files
            for filename in files_to_zip:
                file_path = project_path / filename
                if file_path.exists():
                    tar.add(file_path, arcname=filename)
                    logger.info(f"  ✓ Added: {filename}")
                else:
                    if filename not in [
                        "Dockerfile",
                        ".dockerignore",
                    ]:  # Docker files are optional for the managed sandbox
                        logger.warning(f"  ⚠️  Missing: {filename}")

            # Add optional files
            for filename in optional_files:
                file_path = project_path / filename
                if file_path.exists():
                    tar.add(file_path, arcname=filename)
                    logger.info(f"  ✓ Added: {filename}")

            # Bundle the vendored agentforce_byoc/ SDK package if present.
            # TODO(WI): the SDK is not yet published to PyPI, so projects vendor
            #   the package directory and we ship it inside the archive. Once
            #   agentforce-byoc is on PyPI, drop this and install it via
            #   requirements.txt instead (the runtime pip-installs deps), so
            #   packages don't carry a copy of the SDK.
            vendored_sdk = project_path / "agentforce_byoc"
            if vendored_sdk.is_dir():
                sdk_file_count = 0
                for sdk_path in sorted(vendored_sdk.rglob("*")):
                    # Skip caches/compiled artifacts.
                    if "__pycache__" in sdk_path.parts or sdk_path.suffix == ".pyc":
                        continue
                    if sdk_path.is_file():
                        arcname = str(sdk_path.relative_to(project_path))
                        tar.add(sdk_path, arcname=arcname)
                        sdk_file_count += 1
                logger.info(f"  ✓ Added vendored agentforce_byoc/ ({sdk_file_count} files)")

            # Add dependencies directory
            if dependencies_dir.exists():
                dep_count = 0
                for dep_file in dependencies_dir.iterdir():
                    if dep_file.is_file():
                        arcname = f"dependencies/{dep_file.name}"
                        tar.add(dep_file, arcname=arcname)
                        dep_count += 1
                logger.info(f"  ✓ Added {dep_count} dependency packages")

        # Get archive file size
        zip_size = output_path.stat().st_size
        zip_size_mb = zip_size / (1024 * 1024)

        logger.info("\n✅ Package created successfully!")
        logger.info(f"📦 Output: {output_path}")
        logger.info(f"📊 Size: {zip_size_mb:.2f} MB")

        logger.info("\n🚀 Next step:")
        logger.info(
            "  export ORG_JWT_TOKEN=<jwt> && export SFDC_CORE_TENANT_ID=core/<inst>-<fd>/<org>"
        )
        logger.info(f"  agentforce deploy --package-name <name> --package-file {output_path.name}")

    except Exception as e:
        logger.error(f"❌ Failed to create archive: {e}")
        raise click.Abort()
    finally:
        # Clean up temporary dependencies directory
        if dependencies_dir.exists():
            import shutil

            shutil.rmtree(dependencies_dir)
            logger.debug("🧹 Cleaned up temporary dependencies directory")


@cli.command()
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--output", type=click.Path(), help="Output zip file path")
def package(path: str, output: str):
    """
    Build the agent end-to-end: validate, run, then zip.

    Runs the following commands in sequence:
      1. agentforce validate <path>
      2. agentforce run main.py
      3. agentforce zip --package-dir <path>

    Step 2 runs the agent against the Agentforce BYOC runtime, so ORG_JWT_TOKEN,
    SFDC_CORE_TENANT_ID, SFDC_USER_ID, and SFDC_APP_CONTEXT must be set in the
    environment.

    Example:
        export ORG_JWT_TOKEN=<jwt> && export SFDC_CORE_TENANT_ID=core/<inst>-<fd>/<org>
        export SFDC_USER_ID=<user-id> && export SFDC_APP_CONTEXT=<app-context>
        agentforce package
        agentforce package . --output my-function.tar.gz
    """
    from click import get_current_context

    ctx = get_current_context()

    project_path = Path(path)

    logger.info("📋 Step 1/3: Validating project...")
    ctx.invoke(validate, path=path)

    logger.info("\n🚀 Step 2/3: Running agent...")
    entrypoint = str(project_path / "main.py")
    ctx.invoke(run, entrypoint=entrypoint)

    logger.info("\n📦 Step 3/3: Packaging for deployment...")
    ctx.invoke(zip, package_dir=path, output=output)

    logger.info("\n✅ Package pipeline complete!")


def _resolve_base_url(tenant_id: str) -> str:
    """Resolve the Agentforce BYOC API base URL, aborting on a bad tenant id.

    Prefers ``BYOC_PROXY_URL`` (see :func:`resolve_sfap_base_url`); otherwise
    defaults to production. The tenant id is validated for shape but does not
    select the host.
    """
    try:
        return resolve_sfap_base_url(tenant_id)
    except ValueError as e:
        logger.error(f"❌ Invalid tenant id: {e}")
        raise click.Abort()


def require_env_var(var_name: str, label: str, example: str = "") -> str:
    """
    Return an environment variable's value, or abort with export instructions.

    All commands take the tenant id and org JWT from the environment
    (SFDC_CORE_TENANT_ID, ORG_JWT_TOKEN) rather than CLI flags, so the surface
    is consistent.

    We deliberately do NOT prompt for these values. The org JWT routinely
    exceeds 1024 characters, which is the terminal's canonical-mode line-length
    limit — a typed/pasted line that long can't be submitted (Enter never
    registers). So when a variable is unset we print an `export` instruction
    and abort, which works for a value of any length.
    """
    value = os.getenv(var_name)
    if value:
        return value

    hint = example or "<value>"
    logger.error(f"❌ {var_name} is not set ({label}).")
    logger.info(f"   Set it, then re-run:  export {var_name}={hint}")
    raise click.Abort()


@cli.command()
@click.option("--package-name", required=True, help="Package name")
@click.option(
    "--package-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the package archive produced by 'agentforce zip'",
)
@click.option("--entry-point", default="main.py", help="Function entry point (default: main.py)")
@click.option("--version", default="1.0", help="Package version (default: 1.0)")
@click.option(
    "--max-live-duration",
    default=300,
    type=int,
    help="Max live duration in seconds (default: 300)",
)
def deploy(
    package_name: str,
    package_file: str,
    entry_point: str,
    version: str,
    max_live_duration: int,
):
    """
    Register and upload a packaged agent to the Agentforce BYOC platform.

    Calls <base>/byoc/upload/request, which registers the package metadata
    (size, entry point, max live duration) AND returns a presigned upload URL in
    one step, then uploads the archive to that URL. Poll the result afterward
    with 'agentforce deploy-status'.

    Auth/identity come from environment variables (required; abort if unset):
        - ORG_JWT_TOKEN: org JWT for authentication
        - SFDC_CORE_TENANT_ID: core tenant id (core/<instance>-<fd>/<org-id>)
        - SFDC_USER_ID: caller's user id (sent as x-sfdc-user-id)
        - SFDC_APP_CONTEXT: app context (sent as x-sfdc-app-context)

    The endpoint URL defaults to production. Target another environment by
    exporting BYOC_PROXY_URL (e.g. https://<env>.api.salesforce.com).

    Example:
        export ORG_JWT_TOKEN=<org-jwt>
        export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
        export SFDC_USER_ID=<user-id>
        export SFDC_APP_CONTEXT=<app-context>
        agentforce deploy --package-name test --package-file test-0.1.0.tar.gz
    """
    from agentforce_byoc import deploy_client

    tenant_id = require_env_var(
        "SFDC_CORE_TENANT_ID", "core tenant id", "core/<instance>-<fd>/<org-id>"
    )
    org_jwt = require_env_var("ORG_JWT_TOKEN", "org JWT", "<jwt>")
    user_id = require_env_var("SFDC_USER_ID", "user id", "<user-id>")
    app_context = require_env_var("SFDC_APP_CONTEXT", "app context", "<app-context>")

    package_path = Path(package_file)
    package_size = package_path.stat().st_size
    logger.info(f"Deploying package: {package_name} v{version} (tenant: {tenant_id})")
    logger.info(f"  Entry point: {entry_point}")
    logger.info(f"  Package size: {package_size} bytes")
    logger.info(f"  Max live duration: {max_live_duration}s")

    base_url = _resolve_base_url(tenant_id)
    logger.info(f"  BYOC endpoint: {base_url}/byoc/upload/request")

    # Step 1: register metadata + request a presigned upload URL (one call).
    try:
        presigned = deploy_client.request_presigned_upload(
            base_url=base_url,
            tenant_id=tenant_id,
            org_jwt=org_jwt,
            user_id=user_id,
            app_context=app_context,
            package_name=package_name,
            version=version,
            package_size=package_size,
            entry_points=[entry_point],
            max_live_duration_s=max_live_duration,
        )
    except RuntimeError as e:
        logger.error(f"❌ Failed to register package + request upload URL: {e}")
        raise click.Abort()

    upload_url = presigned.get("uploadUrl")
    s3_key = presigned.get("s3Key")
    if not upload_url:
        logger.error(f"❌ Upload response missing 'uploadUrl': {presigned}")
        raise click.Abort()
    logger.info(f"✓ Registered metadata + received presigned URL (s3Key: {s3_key})")

    # Step 2: upload the package archive to the presigned URL.
    try:
        deploy_client.upload_package(upload_url, package_path)
    except RuntimeError as e:
        logger.error(f"❌ Package upload failed: {e}")
        raise click.Abort()

    logger.info("\n✅ Package deployed successfully!")
    logger.info(f"  Package: {package_name} v{version}")
    logger.info(f"  s3Key: {s3_key}")
    logger.info("\n🔎 Verify it uploaded:")
    logger.info(f"  agentforce deploy-status --package-name {package_name} --version {version}")


@cli.command(name="deploy-status")
@click.option("--package-name", required=True, help="Package name")
@click.option("--version", default="1.0", help="Package version (default: 1.0)")
def deploy_status(package_name: str, version: str):
    """
    Poll deployment status of a package on the Agentforce BYOC platform.

    Calls <base>/byoc/upload/status (read-only) and reports whether the package
    metadata is registered and whether the archive has been uploaded.
    Registration happens during 'agentforce deploy' — this command only reports;
    it never writes.

    Auth/identity come from environment variables (required; abort if unset):
        - ORG_JWT_TOKEN: org JWT for authentication
        - SFDC_CORE_TENANT_ID: core tenant id (core/<instance>-<fd>/<org-id>)
        - SFDC_USER_ID: caller's user id (sent as x-sfdc-user-id)
        - SFDC_APP_CONTEXT: app context (sent as x-sfdc-app-context)

    The endpoint URL defaults to production. Target another environment by
    exporting BYOC_PROXY_URL (e.g. https://<env>.api.salesforce.com).

    Example:
        export ORG_JWT_TOKEN=<org-jwt>
        export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
        export SFDC_USER_ID=<user-id>
        export SFDC_APP_CONTEXT=<app-context>
        agentforce deploy-status --package-name test
    """
    from agentforce_byoc import deploy_client

    tenant_id = require_env_var(
        "SFDC_CORE_TENANT_ID", "core tenant id", "core/<instance>-<fd>/<org-id>"
    )
    org_jwt = require_env_var("ORG_JWT_TOKEN", "org JWT", "<jwt>")
    user_id = require_env_var("SFDC_USER_ID", "user id", "<user-id>")
    app_context = require_env_var("SFDC_APP_CONTEXT", "app context", "<app-context>")

    logger.info(f"Polling upload status: {package_name} v{version} (tenant: {tenant_id})")

    base_url = _resolve_base_url(tenant_id)
    logger.info(f"  BYOC endpoint: {base_url}/byoc/upload/status")

    try:
        status = deploy_client.get_upload_status(
            base_url=base_url,
            tenant_id=tenant_id,
            org_jwt=org_jwt,
            user_id=user_id,
            app_context=app_context,
            package_name=package_name,
            version=version,
        )
    except RuntimeError as e:
        logger.error(f"❌ Failed to poll upload status: {e}")
        raise click.Abort()

    logger.info("\n📦 Deployment status:")
    logger.info(f"  Package: {package_name} v{version}")
    logger.info(f"  s3Key: {status.get('s3Key')}")
    logger.info(f"  Registration: {status.get('registrationStatus')}")
    logger.info(f"  Upload: {status.get('uploadStatus')}")
    if status.get("uploadTime") is not None:
        logger.info(f"  Upload time: {status.get('uploadTime')}")


@cli.command(name="generate-schema")
@click.argument("input", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output", default=None, help="Output YAML file (default: stdout)")
@click.option("--namespace", default=None, help="Function namespace (overrides config file)")
@click.option("--package", default=None, help="Function package (overrides config file)")
@click.option(
    "-c",
    "--config",
    "config_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a YAML or JSON config file with namespace/package",
)
def generate_schema(
    input: str,
    output: str,
    namespace: str,
    package: str,
    config_path: str,
):
    """
    Generate an OpenAPI 3.0 spec from @entry_func functions.

    Scans a Python source file (e.g. main.py) at the AST level — it is never
    imported or executed — for @entry_func functions and their
    @requestSchema/@responseSchema classes, and emits an OpenAPI spec with the
    x-sfdc.code-extension block used for BYOC Code Extension registration.

    Precedence for namespace/package: CLI flags > config file > defaults.

    Example:
        agentforce generate-schema main.py -o MyFunc.yaml --namespace myOrg --package myPkg
    """
    from agentforce_byoc.schema_utils import generator

    ns, pkg = generator.resolve_config(
        cli_namespace=namespace,
        cli_package=package,
        config_path=config_path,
    )

    try:
        yaml_str = generator.generate_schema_yaml(input, namespace=ns, package=pkg)
    except (ValueError, SyntaxError) as e:
        logger.error(f"❌ Failed to generate schema: {e}")
        raise click.Abort()

    if output:
        with open(output, "w") as f:
            f.write(yaml_str)
        logger.info(f"✅ Wrote OpenAPI spec to {output}")
    else:
        click.echo(yaml_str)


def export_requirements(project_path: Path, requirements_path: Path):
    """
    Export requirements.txt from Poetry's lockfile.

    Poetry 2.0+ removed the built-in ``export`` command in favor of the
    ``poetry-plugin-export`` plugin. If the command is missing, this helper
    installs the plugin via ``poetry self add`` and retries once.

    Args:
        project_path: Directory containing pyproject.toml / poetry.lock
        requirements_path: Destination path for the exported requirements.txt

    Raises:
        click.Abort: If the export fails for any reason other than a missing
            plugin, or if installing the plugin does not resolve the issue.
    """
    export_cmd = [
        "poetry",
        "export",
        "-f",
        "requirements.txt",
        "--output",
        str(requirements_path),
        "--without-hashes",
        "--without-urls",
    ]

    def _run_export():
        return subprocess.run(
            export_cmd,
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True,
        )

    try:
        _run_export()
        logger.info("✓ Exported requirements.txt")
        return
    except subprocess.CalledProcessError as e:
        combined = f"{e.stdout or ''}\n{e.stderr or ''}"
        # Poetry 2.x without the export plugin reports the command as unknown.
        if "command export does not exist" not in combined:
            logger.error(f"❌ Failed to export requirements: {e.stderr}")
            logger.info("Make sure poetry.lock exists. Run 'poetry install' first.")
            raise click.Abort()

    # 'poetry export' is unavailable: install the export plugin and retry.
    logger.info("ℹ️  'poetry export' not found (Poetry 2.x). Installing poetry-plugin-export...")
    try:
        subprocess.run(
            ["poetry", "self", "add", "poetry-plugin-export"],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("✓ Installed poetry-plugin-export")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to install poetry-plugin-export: {e.stderr}")
        logger.info("Install it manually: poetry self add poetry-plugin-export")
        raise click.Abort()

    try:
        _run_export()
        logger.info("✓ Exported requirements.txt")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to export requirements after installing plugin: {e.stderr}")
        logger.info("Make sure poetry.lock exists. Run 'poetry install' first.")
        raise click.Abort()


def render_template(template_path: Path, output_path: Path, variables: dict):
    """
    Render a template file with variables.

    Args:
        template_path: Path to template file
        output_path: Path to output file
        variables: Dictionary of template variables
    """
    with open(template_path, "r") as f:
        content = f.read()

    # Simple template rendering (replace {{variable}})
    for key, value in variables.items():
        content = content.replace(f"{{{{{key}}}}}", value)

    with open(output_path, "w") as f:
        f.write(content)


# Runtime subset of the SDK package vendored into each generated project.
# Excludes cli/ (pulls in click; not needed at runtime), templates/, and
# deploy_client.py (only the `agentforce` CLI deploys — packages never do).
_VENDOR_INCLUDE = [
    "__init__.py",
    "client.py",
    "_http.py",
    "logging",
    "runtime",
    "gateway",
    "schema_utils",
]


def vendor_sdk_into_project(project_path: Path) -> int:
    """
    Copy the installed agentforce_byoc runtime package into a generated project.

    TODO(WI): the SDK is not yet published to PyPI, so each generated project
    vendors a copy of the runtime package (and `agentforce zip` ships it inside
    the deployment archive). Once agentforce-byoc is on PyPI, REMOVE this
    vendoring — declare the dependency in the project's pyproject.toml and let
    the runtime install it, so projects don't carry a copy of the SDK.

    Returns:
        The number of files copied (0 if the SDK source can't be located).
    """
    import shutil

    # This module lives at agentforce_byoc/cli/commands.py, so the package root
    # is two parents up.
    sdk_root = Path(__file__).parent.parent
    dest_root = project_path / "agentforce_byoc"

    file_count = 0
    for name in _VENDOR_INCLUDE:
        src = sdk_root / name
        if not src.exists():
            continue
        if src.is_dir():
            for path in sorted(src.rglob("*")):
                if "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                if path.is_file():
                    rel = path.relative_to(sdk_root)
                    out = dest_root / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, out)
                    file_count += 1
        else:
            dest_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_root / name)
            file_count += 1

    return file_count
