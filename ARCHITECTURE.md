# Architecture

This document describes how the Agentforce BYOC Python SDK is structured and how a
request flows through it. For usage, see [README.md](README.md) and
[docs/USAGE_GUIDE.md](docs/USAGE_GUIDE.md).

## Mental model

BYOC = **Bring Your Own Code**. You write a Python function
`function(request: dict) -> dict`. The Agentforce platform runs it inside a managed
sandbox and calls it once per request. The sandbox has no direct outbound network,
so from inside that function your code relays LLM calls back into Agentforce
services through a per-tenant relay client.

## Components

| Layer | Module | Responsibility |
|---|---|---|
| Entry contract | `agentforce_byoc/schema_utils/` | `entry_func`, `requestSchema`, `responseSchema` decorators that mark and validate the agent entry point. |
| Client | `agentforce_byoc/client.py` | `Client` singleton + `get_client()`. Selects the runtime provider on first use. |
| Runtime providers | `agentforce_byoc/runtime/` | `base.py` interface; `agentforce_runtime.py` (default) and `mock_runtime.py`. |
| Relay gateway | `agentforce_byoc/gateway/` | `relay_client.py` (real relay) and `mock_relay_client.py` (local mock), behind `base.py`. |
| HTTP | `agentforce_byoc/_http.py` | Stdlib HTTP that preserves header casing (relay API is case-sensitive). |
| Deploy | `agentforce_byoc/deploy_client.py` | Registers metadata + requests a presigned upload URL in one call, PUTs the archive, and polls status read-only. |
| CLI | `agentforce_byoc/cli/` | `init`, `run`, `validate`, `package`/`zip`, `deploy`, `deploy-status`. |
| Logging | `agentforce_byoc/logging/` | Structured `get_logger`. |

## Runtime selection

The SDK supports two runtimes, chosen on the **first** `get_client()` call and
cached as a singleton:

1. **Agentforce BYOC runtime (default)** — real relay calls; org JWT read from
   `ORG_JWT_TOKEN` (injected by the platform at runtime); endpoint URL resolved
   from the per-call `tenant_id`.
2. **Mock runtime** — selected when `AGENTFORCE_BYOC_MOCK` is truthy; same relay
   surface, org JWT supplied by the author.

Selection is an **environment-variable decision, never a code change** — the same
agent code runs unmodified in either runtime. There is intentionally no CLI flag
for mock mode (it would create a second source of truth).

## Request flow

```
Agentforce platform
        │  invoke (packageName, version, entryPoint)
        ▼
  managed sandbox
        │  calls main() → function(request)
        ▼
  your function ──get_client()──► Client (singleton)
        │                              │ selects provider (env)
        │                              ▼
        │                      RuntimeProvider ──► RelayGatewayClient
        │                                              │ relay LLM call (pass-through `parameter`)
        ▼                                              ▼
   returns dict response                         relay endpoint (BYOC_PROXY_URL, else prod; +/byoc/service if missing)
```

## Deploy flow

`agentforce package` validates and builds a `<name>-<version>.tar.gz` containing
the agent code, the vendored `agentforce_byoc/` SDK, and dependency metadata.
Deployment is one step: `agentforce deploy` `POST`s to `/byoc/upload/request`,
which registers the package metadata **and** returns a presigned upload URL, then
PUTs the archive to that URL. `agentforce deploy-status` is an optional
read-only poll (`GET /byoc/upload/status`) reporting registration + upload
status. Server-side invoke downloads the package, starts a managed sandbox, and
runs `main()`. See [docs/USAGE_GUIDE.md](docs/USAGE_GUIDE.md) Steps 4–6.

## Key invariants

- The real and mock gateway clients are **mirror implementations** — every relay
  method exists in both with the same signature, preserving code portability.
- `parameter` is relayed **unchanged**; the agent author owns model/messages/settings.
- The container runs as **UID/GID 7447** — the only id the platform permits for
  sandboxes.

## Security & trust model

All traffic between the SDK and Agentforce — package deploy, server-side invoke,
and the in-sandbox relay callback — goes over HTTPS through the **Salesforce API
Platform**, the public API gateway at `api.salesforce.com`. Nothing the SDK sends
bypasses that ingress.

**Authentication.** Every request carries the org JWT as an
`Authorization: Bearer` header. The platform validates the token at the gateway;
the SDK never inspects or validates it. The JWT is short-lived (typically hours)
and is read from `ORG_JWT_TOKEN` in the environment on each call — the SDK does
not write it to disk or log it in full (see *Debug output* below).

**Identity.** The caller's org, user, and app context ride along as the
`x-sfdc-core-tenant-id`, `x-sfdc-user-id`, and `x-sfdc-app-context` headers. On
the platform the runtime injects these into the sandbox environment; for local
runs you export them yourself.

**Trust boundary.** Identity is derived from the *validated* org JWT, not from the
caller-supplied headers on their own — the SDK is not a trust anchor. A practical
consequence: a request made with an expired or unauthorized JWT often comes back
as `400 "x-sfdc-core-tenant-id header is required"`. That means the platform could
not resolve the tenant from the token — **not** that the SDK omitted the header.
Retry with a fresh, valid org JWT.

**Relay callback.** The managed sandbox has no direct outbound network. Relay LLM
calls from inside your function go back out to the same public gateway
(`api.salesforce.com`, or `BYOC_PROXY_URL` when set) carrying the same identity
headers, which the runtime injects.

**Debug output.** `AGENTFORCE_BYOC_DEBUG=1` logs the outgoing request and the
response to help diagnose a failed call. The `Authorization` bearer token is
truncated in that output, so enabling debug never prints the full credential.
