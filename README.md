# Agentforce BYOC Python SDK

Python SDK for building custom agents with Agentforce BYOC (Bring Your Own Code).

## Overview

This SDK provides a straightforward way to build agents that integrate with Agentforce. Agents are simple Python functions that receive requests and return responses. The SDK handles relaying LLM calls through the Agentforce platform and structured logging.

## Features

- **Functional API**: Write agents as simple functions
- **Agentforce BYOC runtime**: Relay LLM calls through the Agentforce platform
- **LLM Gateway Integration**: Call language models from the Agentforce runtime
- **Poetry Support**: Modern dependency management
- **CLI Tools**: Commands for project initialization, testing, and deployment

## Requirements

- Python 3.11+
- Poetry for dependency management

## Installation

### From PyPI (available once published)

Once the package is published to PyPI, this is the official way to install the
SDK and its `agentforce` CLI:

```bash
pip install sfdc-agentforce-byoc-python-sdk
```

### Development Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd agentforce-byoc-python-sdk
```

2. Install dependencies:
```bash
make setup
```

3. Verify installation:
```bash
poetry run agentforce --version
```

## Quick Start

### Create a New Agent

```bash
agentforce init my-agent
cd my-agent
poetry install
```

### Write Your Agent

The generated `main.py` provides a working template. The entry point is a
function named `function` decorated with the SDK's schema helpers:

```python
from agentforce_byoc import get_client, get_logger
from agentforce_byoc.schema_utils import entry_func, requestSchema, responseSchema

logger = get_logger(__name__)


@entry_func
@requestSchema(ExampleRequest)
@responseSchema(ExampleResponse)
def function(request: dict) -> dict:
    """Entry point called by the Agentforce BYOC runtime."""
    text = request.get("text", "")
    if not text:
        return {"result": "", "status": "error"}

    # Relay a chat-generations call through the Agentforce Relay API. The
    # tenant id, user id, and app context are read from the environment
    # (SFDC_CORE_TENANT_ID / SFDC_USER_ID / SFDC_APP_CONTEXT), which the
    # runtime injects.
    client = get_client()
    relay_response = client.call_llm_chat_generations(
        parameter={"messages": [{"role": "user", "content": text}]},
    )
    return {"result": str(relay_response), "status": "success"}
```

The template's `main()` builds a sample request (with a `text` placeholder to
fill in) and calls `function(...)` so you can test with `agentforce run`.

### Test Your Agent

Run against the Agentforce BYOC runtime (set auth + tenant + user + app context
first — commands abort if unset):
```bash
export ORG_JWT_TOKEN=<your-org-jwt>
export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
export SFDC_USER_ID=<user-id>
export SFDC_APP_CONTEXT=<app-context>

agentforce run main.py
```

### Package and Deploy

```bash
# Validate your agent
agentforce validate .

# Build end-to-end (validate -> run -> zip)
agentforce package .

# Register + upload to Agentforce BYOC in one step, then poll status
# (set all four identity env vars first; required)
export ORG_JWT_TOKEN=<jwt>
export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
export SFDC_USER_ID=<user-id>
export SFDC_APP_CONTEXT=<app-context>
agentforce deploy --package-name "my-agent" --package-file my-agent-0.1.0.tar.gz
agentforce deploy-status --package-name "my-agent"
```

## API Reference

### `get_client() -> Client`

Returns the singleton Client instance for relaying calls through the Agentforce Relay API.

```python
from agentforce_byoc import get_client

client = get_client()
response = client.call_llm_generations(
    parameter={"prompt": "What is AI?"},
)
```

The client exposes one method per Relay function:
- `call_llm_generations(parameter)` — Relay function `llm`
- `call_llm_chat_generations(parameter)` — Relay function `llm_chat`

`parameter` is the raw request body and is passed through to the Relay API
unchanged. The tenant id, user id, and app context are read from the
environment (`SFDC_CORE_TENANT_ID` / `SFDC_USER_ID` / `SFDC_APP_CONTEXT`),
which the runtime injects in the managed sandbox. The endpoint URL is
`BYOC_PROXY_URL` as-is when it already ends in `/byoc/service` (as the runtime
injects it); otherwise `/byoc/service` is appended to the `BYOC_PROXY_URL` base
host (the same value `deploy` uses) or to `https://api.salesforce.com`.

**Runtime Selection:**
- **Agentforce BYOC runtime** (default): real Relay calls; org JWT from `ORG_JWT_TOKEN` (injected by the runtime)
- **Mock mode**: `AGENTFORCE_BYOC_MOCK` is set (truthy); org JWT supplied by the author (`ORG_JWT_TOKEN`)

### `get_logger(name: str) -> Logger`

Returns a structured logger for your module.

```python
from agentforce_byoc import get_logger

logger = get_logger(__name__)
logger.info("Processing request", extra={"user_id": "123"})
logger.error("Request failed", exc_info=True)
```

## State Management

Use module-level variables to maintain state across requests:

```python
from agentforce_byoc import get_client, get_logger

logger = get_logger(__name__)

# Module-level state persists across function calls
_request_count = 0
_cache = {}

def function(request: dict) -> dict:
    global _request_count
    _request_count += 1

    query = request.get("query", "")

    # Check cache
    if query in _cache:
        return {"response": _cache[query], "cached": True}

    # Relay an LLM generations call
    client = get_client()
    response = client.call_llm_generations(
        parameter={"prompt": query},
    )

    # Update cache
    _cache[query] = response

    return {
        "response": response,
        "cached": False,
        "request_number": _request_count
    }
```

## CLI Commands

### `agentforce init [directory]`

Initialize a new agent project.

```bash
agentforce init my-agent
```

### `agentforce run [entrypoint]`

Run agent locally against the Agentforce BYOC runtime (requires the env vars).

```bash
export ORG_JWT_TOKEN=<your-org-jwt>
export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
export SFDC_USER_ID=<user-id>
export SFDC_APP_CONTEXT=<app-context>
agentforce run main.py
```

### `agentforce validate [path]`

Validate agent before deployment.

```bash
agentforce validate .
```

### `agentforce package [path]`

Build end-to-end (validate → run → zip).

```bash
agentforce package .
agentforce package --output my-agent.tar.gz
```

Auth/identity for `run`, `deploy`, and `deploy-status` come from environment
variables — all four of `ORG_JWT_TOKEN`, `SFDC_CORE_TENANT_ID`
(`core/<instance>-<fd>/<org-id>`), `SFDC_USER_ID`, and `SFDC_APP_CONTEXT`. `run`
relays through the Agentforce service and `deploy`/`deploy-status` call the BYOC
API; both send the user id and app context as `x-sfdc-user-id` /
`x-sfdc-app-context`. If a required var is unset, the command aborts with an
`export` instruction. (They are not prompted: an org JWT exceeds the terminal's
~1024-char line limit, so a typed prompt can't accept it.)

### `agentforce deploy`

Register and upload a packaged agent to Agentforce BYOC. A single
`POST /byoc/upload/request` registers the package metadata (size, entry point,
max live duration) **and** returns a presigned upload URL; the CLI then PUTs the
archive to that URL.

```bash
export ORG_JWT_TOKEN=<jwt>
export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
export SFDC_USER_ID=<user-id>
export SFDC_APP_CONTEXT=<app-context>
agentforce deploy --package-name "my-agent" --package-file my-agent-0.1.0.tar.gz
```

Options: `--package-name` and `--package-file` (required), plus `--entry-point`
(default `main.py`), `--version` (default `1.0`), and `--max-live-duration`
(default `300` seconds).

### `agentforce deploy-status`

Poll deployment status (read-only). Calls `GET /byoc/upload/status` and reports
`registrationStatus` (is the package registered) and `uploadStatus` (has the
archive been uploaded). Registration happens during `deploy`; this command never
writes.

```bash
agentforce deploy-status --package-name "my-agent" --version 1.0
```

## Architecture

### Agent Interface

Agents are implemented as simple functions:

```python
def function(request: dict) -> dict:
    # Your code
    return response
```

The BYOC runtime calls this function for each request. The function receives a dictionary and returns a dictionary response

### Runtime Selection

The SDK supports two runtimes, selected on first `get_client()` call:

1. **Agentforce BYOC Runtime** (default)
   - Real Relay API calls authenticated with the org JWT
   - Org JWT read from `ORG_JWT_TOKEN` (injected by the runtime)
   - Tenant id, user id, and app context read from `SFDC_CORE_TENANT_ID` /
     `SFDC_USER_ID` / `SFDC_APP_CONTEXT` (injected by the runtime); endpoint
     URL from `BYOC_PROXY_URL` (as-is if it ends in `/byoc/service`, else
     with `/byoc/service` appended), else production + `/byoc/service`

2. **Mock Mode**: `AGENTFORCE_BYOC_MOCK` env var is set (truthy)
   - Same relay behavior, with the org JWT supplied by the author
   - JWT from the `MockRelayGatewayClient(org_jwt=...)` arg or `ORG_JWT_TOKEN`
   - Selected via the env var (there is no CLI flag for it)

### Code Portability

Agent code works across both runtimes without modification:

```python
# This code works in both runtimes
def function(request: dict) -> dict:
    client = get_client()  # Selects runtime
    return client.call_llm_generations(...)
```

## Examples

The `examples/` directory contains working examples:

- **01_basic_agent.py** - Minimal functional agent
- **02_llm_agent.py** - LLM Gateway integration
- **03_sentiment_analysis.py** - Sentiment analysis use case
- **04_stateful_agent.py** - State management patterns

Run any example directly. Examples that call the relay need `ORG_JWT_TOKEN`,
`SFDC_CORE_TENANT_ID`, `SFDC_USER_ID`, and `SFDC_APP_CONTEXT` exported;
`01_basic_agent.py` does not call the relay and runs without credentials.

```bash
export ORG_JWT_TOKEN=<your-org-jwt>
export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
export SFDC_USER_ID=<user-id>
export SFDC_APP_CONTEXT=<app-context>
python examples/01_basic_agent.py
python examples/02_llm_agent.py
python examples/03_sentiment_analysis.py
```

See [examples/README.md](examples/README.md) for detailed documentation.

## Development

### Project Structure

```
agentforce-byoc-python-sdk/
├── agentforce_byoc/          # Main package
│   ├── client.py             # Client with runtime selection
│   ├── _http.py              # Stdlib HTTP helper (preserves header casing)
│   ├── deploy_client.py      # /byoc/upload/request + upload/status client
│   ├── runtime/              # Runtime providers
│   │   ├── mock_runtime.py        # Mock provider
│   │   ├── agentforce_runtime.py  # Agentforce provider (default)
│   │   └── base.py                # Base provider interface
│   ├── gateway/              # Relay gateway clients
│   │   ├── relay_client.py        # Agentforce relay client
│   │   ├── mock_relay_client.py   # Mock relay client
│   │   └── base.py                # Base interface
│   ├── schema_utils/         # entry_func / requestSchema / responseSchema
│   ├── logging/              # Structured logging
│   ├── cli/                  # CLI commands
│   └── templates/            # Project templates
├── examples/                 # Working examples
├── tests/                    # Test suite
├── pyproject.toml            # Poetry configuration
└── README.md                 # This file
```

### Running Tests

```bash
poetry run pytest
poetry run pytest --cov=agentforce_byoc
```

### Code Quality

```bash
make format   # black + isort
make lint     # pre-commit: black, isort, ruff, codespell, license header, mypy
```

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the
development workflow, how to write tests, and the contributor/reviewer/trusted-committer
roles. Architecture and design notes live in [ARCHITECTURE.md](ARCHITECTURE.md).

## Support

- **Questions / discussion**: start a [GitHub Discussion](https://github.com/salesforce/agentforce-byoc-python-sdk/discussions).
- **Bugs / feature requests**: file a [GitHub Issue](https://github.com/salesforce/agentforce-byoc-python-sdk/issues).
- **Security vulnerabilities**: follow [SECURITY.md](SECURITY.md) — please don't open a public issue for security reports.

## License & Terms of Use

This project is licensed under the [Apache License 2.0](LICENSE).

Use of this project with Salesforce is subject to the [Terms of Use](TERMS_OF_USE.md).
