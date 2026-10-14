# Agentforce BYOC SDK — Usage Guide

A getting-started guide for engineers who want to run **custom code packages**
on Agentforce, but are new to this SDK. It walks you from zero to a deployed,
running package, explaining what each step does and why.

If you just want the command cheat-sheet, jump to
[The full lifecycle](#the-full-lifecycle-at-a-glance). Otherwise, read top to
bottom — each section builds on the previous one.

---

## What this SDK is (and the mental model)

BYOC = **Bring Your Own Code**. You write a normal Python function; the
Agentforce platform runs it for you inside a managed sandbox, and your code can
call back into Agentforce services (e.g. LLM generations) through a relay.

The flow has two halves:

1. **Author + test locally** — write your function, run it on your laptop.
2. **Deploy + run on the platform** — package it, upload it, and invoke it
   server-side.

Your code is just a function named `function(request: dict) -> dict`. The
platform calls it for each request. To reach Agentforce LLM services from inside
that function, you use the SDK's client:

```python
from agentforce_byoc import get_client

client = get_client()
response = client.call_llm_chat_generations(
    parameter={"messages": [{"role": "user", "content": "Hello"}]},
)
```

There are two relay methods:
- `call_llm_generations(parameter)` — text generations
- `call_llm_chat_generations(parameter)` — chat generations

`parameter` is passed through to the LLM service unchanged, so you control the
model, messages, and generation settings. The tenant id, user id, and app
context are read from the environment (`SFDC_CORE_TENANT_ID` / `SFDC_USER_ID` /
`SFDC_APP_CONTEXT`), which the runtime injects in the sandbox and you export for
local runs.

---

## Prerequisites

### 1. Tooling

- **Python 3.11+**
- **pip**
- **Poetry** (dependency management for the projects you generate)
- This SDK installed with pip. Once the package is published to PyPI, installing
  it puts the `agentforce` CLI on your PATH:

  ```bash
  pip install sfdc-agentforce-byoc-python-sdk
  ```

  Using a virtual environment is recommended so the CLI and its dependencies
  stay isolated from other projects:

  ```bash
  python -m venv .venv
  source .venv/bin/activate
  pip install sfdc-agentforce-byoc-python-sdk
  ```

  Until the PyPI release is available, install from a local clone of the SDK
  repository instead — the same `pip install` mechanism, pointed at the checkout:

  ```bash
  pip install /path/to/agentforce-byoc-python-sdk
  ```

  The package version is derived from git at build time, so the path must be a
  `git clone` checkout (not a ZIP or archive download). To build from a tree
  without git metadata, set `POETRY_DYNAMIC_VERSIONING_BYPASS=<version>` first.

### 2. An org JWT and core tenant id for your org  ← required for any real call

**Every call to an Agentforce BYOC API requires two headers** — an org JWT (for
auth) and the core tenant id (identifies your org):

```
Authorization: Bearer <orgJWT>
x-sfdc-core-tenant-id: <core-tenant-id>
```

The SDK and CLI take these from environment variables:
- `ORG_JWT_TOKEN` — the org JWT
- `SFDC_CORE_TENANT_ID` — the core tenant id, format `core/<instance>-<fd>/<org-id>`
- `SFDC_USER_ID` — the caller's user id (relay calls send it as `x-sfdc-user-id`;
  `agentforce run` requires it too).
- `SFDC_APP_CONTEXT` — the app context (relay calls send it as
  `x-sfdc-app-context`; `agentforce run` requires it too). On the platform the
  runtime injects all four; for local runs you export them yourself.

Two more are **optional** — relay calls forward them only when they're set, and
their absence is never an error:
- `SFDC_FEATURE_ID` — sent as `x-client-feature-id`; the LLM Gateway uses it to
  attribute the call to a feature (for billing).
- `SFDC_TRACE_ID` — sent as `x-b3-traceid`, to propagate the distributed trace.

Export them so the CLI can use them:

```bash
export ORG_JWT_TOKEN='<your org JWT>'
export SFDC_CORE_TENANT_ID='core/<instance>-<fd>/<org-id>'
export SFDC_USER_ID='<your user id>'
export SFDC_APP_CONTEXT='<your app context>'
```

> The CLI does **not** prompt for these — an org JWT is longer than a terminal
> can accept on one input line, so commands that need them abort with an
> `export` instruction if they're unset. Set them once per shell session.

> **Note on the JWT lifetime:** org JWTs expire (typically within a few hours).
> If a previously-working call starts failing auth, `export` a fresh one.

### 3. (For server-side runs) platform provisioning

To actually `deploy` and `invoke` on the platform, the target environment needs
to be provisioned, including the managed sandbox's outbound egress/DNS. (Local
`agentforce run` doesn't need this provisioning, but its relay call does need a
reachable Agentforce service and a valid org JWT.)

---

## Step 1 — Create a project

```bash
agentforce init my-agent
cd my-agent
poetry install
```

`init` scaffolds a ready-to-edit project:

```
my-agent/
├── main.py               # Your function (this is what you edit)
├── entry_func.py         # Entry-point decorator
├── schema.py             # Request/response schema decorators
├── agentforce_byoc/      # Vendored SDK (until it's published to PyPI)
├── config.json           # Function metadata (entryPoint)
├── Dockerfile            # Container definition
├── pyproject.toml        # Dependencies (Poetry)
└── README.md
```

The generated `main.py` already contains a working example that relays a chat
call. Open it and look at `function(...)` — that's your entry point.

> **Why `agentforce_byoc/` is copied in:** the SDK isn't on PyPI yet, so each
> project vendors a copy. This is what lets your deployed package
> `import agentforce_byoc` inside the sandbox. Once the SDK is published, this
> directory goes away and you'll declare it as a normal dependency instead.

---

## Step 2 — Write your function

Edit `main.py`. The contract is simple: a function that takes a `dict` and
returns a `dict`.

```python
from agentforce_byoc import get_client, get_logger
from agentforce_byoc.schema_utils import entry_func, requestSchema, responseSchema

logger = get_logger(__name__)


_DEFAULT_PROMPT = "Hello, Agentforce, What is the best place to eat dumplings in Seattle!"


@entry_func
@requestSchema(ExampleRequest)
@responseSchema(ExampleResponse)
def function(request: dict) -> dict:
    # Missing, null, or empty `text` is an invalid invoke: return an input error
    # instead of calling the relay, so an empty invocation never incurs model
    # traffic. (`_DEFAULT_PROMPT` is only for local runs via `main()`.)
    text = request.get("text")
    if not text:
        return {"result": "", "status": "error"}

    # The tenant id, user id, and app context are read from the environment
    # (SFDC_CORE_TENANT_ID / SFDC_USER_ID / SFDC_APP_CONTEXT), which the
    # runtime injects.
    client = get_client()
    relay_response = client.call_llm_chat_generations(
        parameter={
            "messages": [{"role": "user", "content": text}],
            "generation_settings": {"max_tokens": 50},
            "model": "llmgateway__EinsteinLlama4Maverick",
        },
    )
    return {"result": str(relay_response), "status": "success"}
```

The `main()` at the bottom of the file is the local test harness. It reads the
invoke's `input` payload from a module global named `byoc_input` (which the
platform binds before running your file). When you run locally that global is
**unbound**, so `main()` falls back to a sample request `{"text": _DEFAULT_PROMPT}`.
Edit `_DEFAULT_PROMPT` (or the sample request in `main()`) to change what a local
run sends.

> **Why a sentinel, not `byoc_input or {...}`:** `main()` distinguishes "the
> runtime never bound the global" (local run → use the sample) from "the runtime
> bound it to `{}`/`None`" (a real invoke → respect it as-is). That's why an
> in-runtime invoke with an empty input never silently runs the local sample.

---

## Step 3 — Run locally

`agentforce run` executes your function on your machine; any relay calls it
makes go out to the real Agentforce service. So you need credentials set first
(the command aborts with instructions if they're unset):

```bash
export ORG_JWT_TOKEN='<jwt>'
export SFDC_CORE_TENANT_ID='core/<instance>-<fd>/<org-id>'
export SFDC_USER_ID='<user-id>'
export SFDC_APP_CONTEXT='<app-context>'
agentforce run main.py
```

This is the quickest way to confirm your prompt/model actually work before
deploying — you iterate on `main.py` and re-run, all on your laptop, without
the package/deploy round-trip.

> `agentforce run` simply executes the file (`python main.py` → `main()`), so
> the input is whatever your `main()` passes to `function(...)`. To change the
> test input, edit `_DEFAULT_PROMPT` (or the sample `request` in `main()`).

---

## Step 4 — Validate and package

When the function works locally, package it for deployment.

```bash
# Optional: check the project has everything it needs
agentforce validate .

# Build the deployment archive (a gzip tar)
agentforce zip .
```

`zip` produces `<name>-<version>.tar.gz` containing your code, the vendored SDK,
and dependency metadata. There's also a fuller command that runs
validate → run → **download-and-bundle third-party deps** → zip in sequence (its
run step needs `ORG_JWT_TOKEN` + `SFDC_CORE_TENANT_ID` + `SFDC_USER_ID` +
`SFDC_APP_CONTEXT` set, same as `agentforce run`):

```bash
agentforce package .
```

> **`package` uses `pip` to bundle dependencies.** Its bundling step downloads
> your project's third-party dependencies into the archive via `pip`. If `pip`
> isn't available you'll see `❌ Error bundling dependencies: [Errno 2] No such
> file or directory: 'pip'` — install/enable pip (see Prerequisites) and re-run.
>
> **When your project has no third-party runtime dependencies, prefer `zip`.**
> `zip` skips the bundling step entirely, so there's nothing for `package` to add
> — and no `pip` requirement.

---

## Step 5 — Deploy

Deployment is **one command** plus an optional status check. `agentforce deploy`
registers the package metadata **and** uploads the archive in a single flow: it
`POST`s to `/byoc/upload/request` (which registers the metadata *and* returns a
presigned upload URL), then PUTs the archive to that URL. `agentforce deploy-status`
is a read-only poll. Both read the same four identity vars as `agentforce run`
from the environment (`ORG_JWT_TOKEN`, `SFDC_CORE_TENANT_ID`, `SFDC_USER_ID`,
`SFDC_APP_CONTEXT`) and send the user id + app context as `x-sfdc-user-id` /
`x-sfdc-app-context`.

```bash
export ORG_JWT_TOKEN='<jwt>'
export SFDC_CORE_TENANT_ID='core/<instance>-<fd>/<org-id>'
export SFDC_USER_ID='<user-id>'
export SFDC_APP_CONTEXT='<app-context>'

# 1. Register + upload: registers metadata (size, entry point, max live
#    duration) and PUTs the archive to the returned presigned upload URL
agentforce deploy --package-name my-agent --package-file my-agent-0.1.0.tar.gz

# 2. (Optional) Poll status — read-only: reports registrationStatus + uploadStatus
agentforce deploy-status --package-name my-agent --version 1.0
```

> **Package name rules:** letters, digits, hyphens, underscores — **no dots**.
> So `my-agent` is valid; `my-agent-0.1.0` is not (the version is separate, via
> `--version`, default `1.0`). The `.tar.gz` filename is unrelated to the
> package name.

> **`deploy` options:** `--entry-point` (default `main.py`), `--version`
> (default `1.0`), and `--max-live-duration` (default `300` seconds) travel with
> `deploy`, which is where the metadata is registered. `deploy-status` takes only
> `--package-name` and `--version` — it reports, never writes.

---

## Step 6 — Invoke (run on the platform)

Once deployed, invoke the package server-side. The platform downloads it, starts
a sandbox, and runs your `main()`:

```bash
 curl -X POST 'https://api.salesforce.com/byoc/invoke/run/package/{package-name}' \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $ORG_JWT_TOKEN" \
    -H "x-sfdc-core-tenant-id: $SFDC_CORE_TENANT_ID" \
    -H "x-sfdc-user-id: $SFDC_USER_ID" \
    -H "x-sfdc-app-context: $SFDC_APP_CONTEXT" \
    -d '{"version": "1.0", "entryPoint": "main.py", "input": {"text":"Dumpling restaurants recommendations in Seattle"}}'
```

The host defaults to production (`api.salesforce.com`); set `BYOC_PROXY_URL` to
target a different environment. The response is `{taskId, sessionId, status,
output}`, with your function's stdout in `output`.

> Inside the sandbox, your function's relay call goes back out to the Agentforce
> service. That requires the sandbox to have outbound egress + DNS provisioned
> for the environment. If it isn't, the invoke returns 200 but `output` contains
> a DNS resolution error — that's an environment setup gap, not a code bug.

---

## The full lifecycle at a glance

```bash
# One-time per shell session
export ORG_JWT_TOKEN='<jwt>'
export SFDC_CORE_TENANT_ID='core/<instance>-<fd>/<org-id>'
export SFDC_USER_ID='<user-id>'       # required by run + deploy + deploy-status
export SFDC_APP_CONTEXT='<app-context>'  # required by run + deploy + deploy-status

# Author
agentforce init my-agent && cd my-agent && poetry install
#   ...edit main.py...

# Test locally (uses the env vars above)
agentforce run main.py

# Package
agentforce zip .                   # or: agentforce package .

# Deploy (register + upload in one step; then optionally poll status)
agentforce deploy        --package-name my-agent --package-file my-agent-0.1.0.tar.gz
agentforce deploy-status --package-name my-agent --version 1.0

# Invoke on the platform (host defaults to api.salesforce.com;
# set BYOC_PROXY_URL to target a different environment)
curl -X POST 'https://<host>/byoc/invoke/run/package/{package-name}' \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $ORG_JWT_TOKEN" \
    -H "x-sfdc-core-tenant-id: $SFDC_CORE_TENANT_ID" \
    -H "x-sfdc-user-id: $SFDC_USER_ID" \
    -H "x-sfdc-app-context: $SFDC_APP_CONTEXT" \
    -d '{"version": "1.0", "entryPoint": "main.py", "input": {"text":"Dumpling restaurants recommendations in Seattle"}}'
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `command not found: agentforce` | The SDK isn't installed in the active environment | `pip install sfdc-agentforce-byoc-python-sdk` (see Prerequisites → Tooling); if using a virtual environment, activate it first. |
| `❌ Error bundling dependencies: [Errno 2] No such file or directory: 'pip'` (during `package`) | `pip` isn't available in the active environment | Ensure `pip` is installed/enabled. Or, if the project has no third-party deps, use `agentforce zip` instead — it skips bundling. |
| `ORG_JWT_TOKEN is not set` / `SFDC_CORE_TENANT_ID is not set` / `SFDC_USER_ID is not set` / `SFDC_APP_CONTEXT is not set` (command aborts) | Env vars not exported (`run`, `deploy`, and `deploy-status` each need all four) | `export` the missing var (see Prerequisites). |
| `401` / auth failure on a previously-working call | Org JWT expired | Get a fresh org JWT and re-`export` it. |
| `400 Invalid package name format` | Package name contains a dot or other invalid char | Use letters/digits/`-`/`_` only; put the version in `--version`. |
| `404 ... not found. Upload it first` on invoke | No metadata for that `(packageName, version)` | Run `deploy` first; confirm with `deploy-status` (should show `registered` + `uploaded`); check name/version match. |
| `ModuleNotFoundError: No module named 'agentforce_byoc'` at run | The vendored SDK dir is missing from the package | Re-run `agentforce zip` (it bundles `agentforce_byoc/`); re-deploy. |

---

## Where to go next

- **`README.md`** — command reference and API summary.
