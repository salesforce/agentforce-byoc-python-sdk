# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Main CLI entry point for Agentforce BYOC SDK."""

import click

from agentforce_byoc import __version__


@click.group()
@click.version_option(version=__version__)
def cli():
    """
    Agentforce BYOC SDK - Build and deploy custom agents.

    Commands:
      init           Initialize a new agent project
      run            Run agent locally against the Agentforce runtime
      validate       Validate agent before deployment
      zip            Create a deployment-ready package archive
      package        Build end-to-end: validate -> run -> zip
      deploy         Register + upload a packaged agent to Agentforce BYOC
      deploy-status  Poll deployment status (read-only)
      generate-schema  Generate an OpenAPI spec from @entry_func functions

    Auth/identity for run + deploy + deploy-status come from env vars (required;
    abort if unset): ORG_JWT_TOKEN, SFDC_CORE_TENANT_ID
      (core/<instance>-<fd>/<org-id>), SFDC_USER_ID, SFDC_APP_CONTEXT.

    Examples:
      agentforce init my-agent
      agentforce run main.py
      agentforce zip
      agentforce package
      export ORG_JWT_TOKEN=<jwt> && export SFDC_CORE_TENANT_ID=core/<inst>-<fd>/<org> && export SFDC_USER_ID=<user-id> && export SFDC_APP_CONTEXT=<app-context>
      agentforce deploy --package-name test --package-file test-0.1.0.tar.gz
      agentforce deploy-status --package-name test --version 1.0
    """
    pass


# Import commands to register them with the CLI group
from agentforce_byoc.cli import commands  # noqa: E402, F401
