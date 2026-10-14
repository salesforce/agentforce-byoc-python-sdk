# Contributing to Agentforce BYOC Python SDK

Contributions are welcome. This guide covers setup, the development workflow, how
to write tests, and the roles involved in reviewing and merging changes.

## Getting Started

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/) for dependency management

### Setup

```bash
git clone https://github.com/salesforce/agentforce-byoc-python-sdk.git
cd agentforce-byoc-python-sdk
make setup            # creates .venv and runs `poetry install --with dev,test`
source .venv/bin/activate
```

### Verify Your Setup

```bash
make test             # runs pytest with coverage
```

If the suite passes, you're ready to contribute.

## Development Workflow

1. Create a branch: `git checkout -b feature/your-feature`
2. Make your changes (see [ARCHITECTURE.md](ARCHITECTURE.md) for the design and
   package layout).
3. Run the fast test loop while iterating: `make test-quick`
4. Before pushing, run the full gate (`git add` new files first; pre-commit only
   checks files git tracks):
   ```bash
   make lint          # pre-commit: black, isort, ruff, codespell, license header, mypy
   make test          # pytest + coverage
   ```
5. Format any drift: `make format`
6. Commit, push, and open a pull request (see the PR template).

## Documentation & Comment Guidelines

This is a **customer-facing, open-source SDK.** Every comment, docstring, log
message, and doc is public. Write them for an SDK consumer who has no visibility
into Salesforce-internal services or infrastructure — expose only what helps them
*use* the SDK, and never internal implementation detail.

**All comments and docstrings must be public and customer-facing.** Concretely:

- Describe observable behavior, the public API, env vars, header names, endpoint
  paths, hostnames, and error conditions a consumer will actually hit.
- Do **not** name internal services, components, or their infrastructure. Refer to
  the backend generically (e.g. "the Agentforce BYOC platform", "the managed
  sandbox") rather than internal service names, routing layers, storage systems,
  or launcher components.
- Do **not** narrate server-side internals (how a request is verified/routed,
  where data is stored, network topology, control-plane mechanics).
- Keep the *reason* a consumer needs (e.g. "the managed sandbox has no direct
  outbound network, so relay calls go through the SDK client") without the
  internal detail behind it.

### Technical / documentation scrub ⚠️

Before opening a PR — and required before any open-source release — verify these
hard blockers. A PR that trips any ⚠️ item must not merge:

- ⚠️ **No hard-coded credentials** (auth tokens, org JWTs, secrets, etc.).
- ⚠️ **No private/internal API usage.**
- ⚠️ **No non-public system/deploy info** (infra specs, internal hostnames beyond
  the public API endpoints, deploy topology, etc.).
- **Remove critical dependencies on non-public components;** strip internal
  comments and references to internal code.
- **README covering Installation, Usage, and Testing** stays accurate.

## Writing Tests

Test guidance — expand a contribution from "I changed code" to "I changed code and proved it":

- **Placement & naming**: tests live in `tests/`, named `test_*.py` or `*_test.py`
  (configured in `pytest.ini` / `pyproject.toml` `[tool.pytest.ini_options]`).
- **Run a single test**:
  ```bash
  poetry run pytest tests/test_init.py::test_version -vv
  ```
- **Run everything**: `make test` (with coverage) or `make test-quick` (without).
- **Fixtures / utilities**: the autouse `reset_client_singleton` fixture in
  `tests/test_init.py` resets the `Client` singleton before and after each test —
  rely on it so runtime-selection state doesn't leak between tests.
- **Mock mode**: force the mock runtime with `AGENTFORCE_BYOC_MOCK=1`, or
  instantiate `MockRelayGatewayClient(org_jwt=...)` directly. Any new relay method
  must be tested against **both** the real and mock clients (they are mirror
  implementations).
- **Example test** (from `tests/test_init.py`):
  ```python
  def test_version():
      """Test that version is defined."""
      # The concrete value is injected at build time by poetry-dynamic-versioning;
      # in a source checkout it is the "0.0.0" placeholder.
      assert isinstance(__version__, str)
      assert __version__
  ```

## Roles

| Role | Responsibilities |
|---|---|
| **Contributor** | Anyone opening a PR. Writes code/docs, adds tests, runs `make lint && make test` before pushing, and responds to review feedback. |
| **Reviewer** | A team member who reviews a PR for correctness, test coverage, and adherence to the patterns in [ARCHITECTURE.md](ARCHITECTURE.md). Routed via [CODEOWNERS](CODEOWNERS). |
| **Trusted Committer / Maintainer** | Owns the repo direction, has merge rights, triages incoming work, and is the escalation point listed in [CODEOWNERS](CODEOWNERS). |

## Code Review

- Every PR needs at least one approving review from a code owner before merge.
- CI (GitHub Actions, [`.github/workflows/ci.yml`](.github/workflows/ci.yml)) must be
  green — it runs the lint, test+coverage, and build jobs on every pull request.
- Keep PRs focused; link any related issue in the PR description.

## Where to Get Help

See the [Support section of the README](README.md#support) for where to ask
questions ([GitHub Discussions](https://github.com/salesforce/agentforce-byoc-python-sdk/discussions))
and report bugs ([GitHub Issues](https://github.com/salesforce/agentforce-byoc-python-sdk/issues)).
