# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Basic tests for Agentforce BYOC SDK."""

import pytest

from agentforce_byoc import __version__, get_client, get_logger
from agentforce_byoc.client import Client
from agentforce_byoc.gateway import AgentforceRelayGatewayClient, MockRelayGatewayClient
from agentforce_byoc.gateway.relay_client import (
    CORE_TENANT_ID_ENV_VAR,
    FEATURE_ID_ENV_VAR,
    ORG_JWT_ENV_VAR,
    PROXY_URL_ENV_VAR,
    TRACE_ID_ENV_VAR,
    USER_ID_ENV_VAR,
    resolve_relay_url,
    resolve_sfap_base_url,
)

VALID_TENANT = "core/instance-core4/00Dxx0000000000"
VALID_USER_ID = "005xx000001234567"
VALID_APP_CONTEXT = "EinsteinGPT"
# Distinct from the production default so tests can prove BYOC_PROXY_URL
# overrides it.
VALID_PROXY_URL = "https://custom.proxy.example"
# The base URL used when BYOC_PROXY_URL is not set.
PROD_BASE_URL = "https://api.salesforce.com"


@pytest.fixture(autouse=True)
def reset_client_singleton():
    """Reset the Client singleton before and after each test."""
    Client.reset()
    yield
    Client.reset()


def test_version():
    """Test that version is defined."""
    # The concrete value is injected at build time by poetry-dynamic-versioning;
    # in a source checkout it is the "0.0.0" placeholder.
    assert isinstance(__version__, str)
    assert __version__


def test_get_logger():
    """Test that get_logger returns a logger instance."""
    logger = get_logger(__name__)
    assert logger is not None
    assert hasattr(logger, "info")
    assert hasattr(logger, "error")
    assert hasattr(logger, "warning")


# ---------------------------------------------------------------------------
# Runtime selection
# ---------------------------------------------------------------------------


def test_default_runtime_is_agentforce(monkeypatch):
    """Without AGENTFORCE_BYOC_MOCK, the default runtime is Agentforce."""
    monkeypatch.delenv("AGENTFORCE_BYOC_MOCK", raising=False)
    client = get_client()
    assert client.runtime.name == "agentforce"


def test_mock_mode_runtime(monkeypatch):
    """AGENTFORCE_BYOC_MOCK selects the mock runtime."""
    monkeypatch.setenv("AGENTFORCE_BYOC_MOCK", "1")
    client = get_client()
    assert client.runtime.name == "mock"


def test_get_client_singleton(monkeypatch):
    """get_client returns the same instance."""
    monkeypatch.setenv("AGENTFORCE_BYOC_MOCK", "1")
    assert get_client() is get_client()


# ---------------------------------------------------------------------------
# SFAP URL resolution
# ---------------------------------------------------------------------------


def test_resolve_sfap_base_url_prefers_env(monkeypatch):
    """BYOC_PROXY_URL takes precedence; the tenant id is ignored."""
    monkeypatch.setenv(PROXY_URL_ENV_VAR, VALID_PROXY_URL)
    # The env var wins; the tenant id doesn't select the host.
    assert resolve_sfap_base_url(VALID_TENANT) == VALID_PROXY_URL


def test_resolve_sfap_base_url_env_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv(PROXY_URL_ENV_VAR, VALID_PROXY_URL + "/")
    assert resolve_sfap_base_url(VALID_TENANT) == VALID_PROXY_URL


@pytest.mark.parametrize(
    "tenant_id",
    [
        "core/instance-core4/00Dxx",
        "core/instancea/00Dxx",
        "core/instance1-ora3/00Dxx",
        "core/prod/00Dxx",
        # Any well-formed instance now resolves to production; the instance
        # token no longer selects the host.
        "core/anyinstance-core9/00Dxx",
        # Instance token without an -fd suffix is still well-formed.
        "core/instance/00Dxx",
    ],
)
def test_resolve_sfap_base_url_defaults_to_prod(monkeypatch, tenant_id):
    """Without BYOC_PROXY_URL, any well-formed tenant resolves to production."""
    monkeypatch.delenv(PROXY_URL_ENV_VAR, raising=False)
    assert resolve_sfap_base_url(tenant_id) == PROD_BASE_URL


@pytest.mark.parametrize(
    "tenant_id",
    [
        "",
        "garbage",
        "notcore/instance-core4/00Dxx",  # wrong prefix
        "core/instance-core4",  # missing org segment
        "core//00Dxx",  # empty instance
    ],
)
def test_resolve_sfap_base_url_rejects_bad_tenant(monkeypatch, tenant_id):
    """On the default path (no BYOC_PROXY_URL), a malformed tenant id raises.

    An unknown-but-well-formed instance is NOT rejected anymore — the host is
    always production unless BYOC_PROXY_URL overrides it.
    """
    monkeypatch.delenv(PROXY_URL_ENV_VAR, raising=False)
    with pytest.raises(ValueError):
        resolve_sfap_base_url(tenant_id)


# ---------------------------------------------------------------------------
# Relay endpoint URL resolution (full path, with the /byoc/service suffix)
# ---------------------------------------------------------------------------


def test_resolve_relay_url_appends_suffix_to_env_base(monkeypatch):
    """A BYOC_PROXY_URL without /byoc/service is a base host; the suffix is appended.

    The same value the deploy CLI uses locally (a base host, no path) must also
    work for the relay.
    """
    monkeypatch.setenv(PROXY_URL_ENV_VAR, VALID_PROXY_URL)
    assert resolve_relay_url(VALID_TENANT) == f"{VALID_PROXY_URL}/byoc/service"


def test_resolve_relay_url_env_base_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv(PROXY_URL_ENV_VAR, f"{VALID_PROXY_URL}/")
    assert resolve_relay_url(VALID_TENANT) == f"{VALID_PROXY_URL}/byoc/service"


def test_resolve_relay_url_env_not_doubled(monkeypatch):
    """A BYOC_PROXY_URL already ending in /byoc/service is used as-is.

    The Agentforce runtime injects BYOC_PROXY_URL into the managed sandbox
    already pointing at .../byoc/service. Appending /byoc/service again would
    yield .../byoc/service/byoc/service and a 404.
    """
    full = f"{VALID_PROXY_URL}/byoc/service"
    monkeypatch.setenv(PROXY_URL_ENV_VAR, full)
    assert resolve_relay_url(VALID_TENANT) == full


def test_resolve_relay_url_env_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv(PROXY_URL_ENV_VAR, f"{VALID_PROXY_URL}/byoc/service/")
    assert resolve_relay_url(VALID_TENANT) == f"{VALID_PROXY_URL}/byoc/service"


def test_resolve_relay_url_appends_suffix_on_default(monkeypatch):
    """Without BYOC_PROXY_URL, the production default gets /byoc/service."""
    monkeypatch.delenv(PROXY_URL_ENV_VAR, raising=False)
    assert resolve_relay_url("core/instance1-core4/00Dxx") == f"{PROD_BASE_URL}/byoc/service"


def test_resolve_relay_url_rejects_bad_tenant_on_fallback(monkeypatch):
    """Without BYOC_PROXY_URL, a bad tenant id raises (via the base resolver)."""
    monkeypatch.delenv(PROXY_URL_ENV_VAR, raising=False)
    with pytest.raises(ValueError):
        resolve_relay_url("garbage")


# ---------------------------------------------------------------------------
# Request construction + JWT source
# ---------------------------------------------------------------------------


def test_build_request_body():
    client = AgentforceRelayGatewayClient()
    body = client._build_request_body("llm", {"prompt": "hi"})
    # Relay body carries only function + parameter; tenant/JWT go in headers.
    assert body == {
        "function": "llm",
        "parameter": {"prompt": "hi"},
    }


def test_agentforce_jwt_from_env(monkeypatch):
    monkeypatch.setenv(ORG_JWT_ENV_VAR, "env-jwt")
    assert AgentforceRelayGatewayClient()._get_org_jwt() == "env-jwt"


def test_agentforce_jwt_missing_raises(monkeypatch):
    monkeypatch.delenv(ORG_JWT_ENV_VAR, raising=False)
    with pytest.raises(RuntimeError):
        AgentforceRelayGatewayClient()._get_org_jwt()


def test_mock_jwt_from_constructor(monkeypatch):
    monkeypatch.delenv(ORG_JWT_ENV_VAR, raising=False)
    assert MockRelayGatewayClient(org_jwt="ctor-jwt")._get_org_jwt() == "ctor-jwt"


def test_mock_jwt_falls_back_to_env(monkeypatch):
    monkeypatch.setenv(ORG_JWT_ENV_VAR, "env-jwt")
    assert MockRelayGatewayClient()._get_org_jwt() == "env-jwt"


def test_mock_jwt_missing_raises(monkeypatch):
    monkeypatch.delenv(ORG_JWT_ENV_VAR, raising=False)
    with pytest.raises(RuntimeError):
        MockRelayGatewayClient()._get_org_jwt()


# ---------------------------------------------------------------------------
# Relay dispatch (transport mocked)
# ---------------------------------------------------------------------------


def _capture_post(client):
    """Patch _post on a client to capture call args and return a sentinel."""
    captured = {}

    def fake_post(function, body, org_jwt):
        captured["function"] = function
        captured["body"] = body
        captured["org_jwt"] = org_jwt
        return {"body": {"ok": True}, "requestId": "r1", "traceId": "t1"}

    client._post = fake_post
    return captured


def test_call_llm_generations_dispatch(monkeypatch):
    monkeypatch.setenv(ORG_JWT_ENV_VAR, "env-jwt")
    monkeypatch.setenv(CORE_TENANT_ID_ENV_VAR, VALID_TENANT)
    monkeypatch.setenv(USER_ID_ENV_VAR, VALID_USER_ID)
    client = AgentforceRelayGatewayClient()
    captured = _capture_post(client)

    result = client.call_llm_generations({"prompt": "hi"})

    assert captured["function"] == "llm"
    # Body carries only function + parameter; tenant/JWT/user travel as headers.
    assert captured["body"] == {"function": "llm", "parameter": {"prompt": "hi"}}
    # The org JWT is resolved from the environment; _post resolves the tenant
    # (and thus the URL), app context, and user id itself (URL + headers are
    # asserted in test_relay_post_sends_required_headers).
    assert captured["org_jwt"] == "env-jwt"
    assert result == {"body": {"ok": True}, "requestId": "r1", "traceId": "t1"}


def test_call_llm_chat_generations_dispatch(monkeypatch):
    monkeypatch.setenv(ORG_JWT_ENV_VAR, "env-jwt")
    monkeypatch.setenv(CORE_TENANT_ID_ENV_VAR, VALID_TENANT)
    monkeypatch.setenv(USER_ID_ENV_VAR, VALID_USER_ID)
    client = AgentforceRelayGatewayClient()
    captured = _capture_post(client)

    client.call_llm_chat_generations({"messages": []})

    assert captured["function"] == "llm_chat"
    assert captured["body"] == {"function": "llm_chat", "parameter": {"messages": []}}
    assert captured["org_jwt"] == "env-jwt"


def test_relay_post_sends_required_headers(monkeypatch):
    """_post must send Authorization, tenant, app-context, and user id.

    The proxy relay endpoint returns 400 header_invalid without
    x-sfdc-app-context, so the SDK forwards SFDC_APP_CONTEXT (injected into the
    sandbox) on every relay call. The tenant and user id are likewise resolved
    from the injected environment and sent as headers.
    """
    monkeypatch.setenv(ORG_JWT_ENV_VAR, "env-jwt")
    monkeypatch.setenv(CORE_TENANT_ID_ENV_VAR, VALID_TENANT)
    monkeypatch.setenv(USER_ID_ENV_VAR, VALID_USER_ID)
    monkeypatch.setenv(PROXY_URL_ENV_VAR, VALID_PROXY_URL)
    monkeypatch.setenv("SFDC_APP_CONTEXT", "MyApp")
    calls = _capture_http(
        monkeypatch, response_payload={"body": {}, "requestId": "r", "traceId": "t"}
    )

    AgentforceRelayGatewayClient().call_llm_chat_generations({"messages": []})

    # VALID_PROXY_URL has no /byoc/service suffix, so it is treated as a base
    # host and /byoc/service is appended.
    assert calls[0]["url"] == f"{VALID_PROXY_URL}/byoc/service"
    headers = calls[0]["headers"]
    assert headers["Authorization"] == "Bearer env-jwt"
    assert headers["x-sfdc-core-tenant-id"] == VALID_TENANT
    assert headers["x-sfdc-app-context"] == "MyApp"
    assert headers["x-sfdc-user-id"] == VALID_USER_ID


def _set_required_relay_env(monkeypatch):
    """Set the mandatory relay identity env vars (feature/trace id left to caller)."""
    monkeypatch.setenv(ORG_JWT_ENV_VAR, "env-jwt")
    monkeypatch.setenv(CORE_TENANT_ID_ENV_VAR, VALID_TENANT)
    monkeypatch.setenv(USER_ID_ENV_VAR, VALID_USER_ID)
    monkeypatch.setenv(PROXY_URL_ENV_VAR, VALID_PROXY_URL)
    monkeypatch.setenv("SFDC_APP_CONTEXT", "MyApp")


def test_relay_post_forwards_optional_client_context_headers(monkeypatch):
    """When SFDC_FEATURE_ID / SFDC_TRACE_ID are set, _post forwards them as the
    x-client-feature-id / x-b3-traceid headers (LLM-GW feature attribution and
    B3 trace propagation). Header names are case-sensitive.
    """
    _set_required_relay_env(monkeypatch)
    monkeypatch.setenv(FEATURE_ID_ENV_VAR, "my-feature")
    monkeypatch.setenv(TRACE_ID_ENV_VAR, "0af7651916cd43dd8448eb211c80319c")
    calls = _capture_http(
        monkeypatch, response_payload={"body": {}, "requestId": "r", "traceId": "t"}
    )

    AgentforceRelayGatewayClient().call_llm_chat_generations({"messages": []})

    headers = calls[0]["headers"]
    assert headers["x-client-feature-id"] == "my-feature"
    assert headers["x-b3-traceid"] == "0af7651916cd43dd8448eb211c80319c"


def test_relay_post_omits_optional_headers_when_unset(monkeypatch):
    """Optional client-context headers are absent entirely when their env vars
    are unset — an agent that never sets them is unaffected.
    """
    _set_required_relay_env(monkeypatch)
    monkeypatch.delenv(FEATURE_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(TRACE_ID_ENV_VAR, raising=False)
    calls = _capture_http(
        monkeypatch, response_payload={"body": {}, "requestId": "r", "traceId": "t"}
    )

    AgentforceRelayGatewayClient().call_llm_generations({"prompt": "hi"})

    headers = calls[0]["headers"]
    assert "x-client-feature-id" not in headers
    assert "x-b3-traceid" not in headers


def test_relay_post_forwards_only_the_optional_header_that_is_set(monkeypatch):
    """Each optional header is independent: setting feature id but not trace id
    forwards only x-client-feature-id.
    """
    _set_required_relay_env(monkeypatch)
    monkeypatch.setenv(FEATURE_ID_ENV_VAR, "just-feature")
    monkeypatch.delenv(TRACE_ID_ENV_VAR, raising=False)
    calls = _capture_http(
        monkeypatch, response_payload={"body": {}, "requestId": "r", "traceId": "t"}
    )

    AgentforceRelayGatewayClient().call_llm_generations({"prompt": "hi"})

    headers = calls[0]["headers"]
    assert headers["x-client-feature-id"] == "just-feature"
    assert "x-b3-traceid" not in headers


def test_relay_post_treats_blank_optional_env_as_unset(monkeypatch):
    """A blank/whitespace-free empty value is treated as unset (header omitted),
    matching the ``os.getenv(...) or None`` contract in the getters.
    """
    _set_required_relay_env(monkeypatch)
    monkeypatch.setenv(FEATURE_ID_ENV_VAR, "")
    monkeypatch.setenv(TRACE_ID_ENV_VAR, "")
    calls = _capture_http(
        monkeypatch, response_payload={"body": {}, "requestId": "r", "traceId": "t"}
    )

    AgentforceRelayGatewayClient().call_llm_generations({"prompt": "hi"})

    headers = calls[0]["headers"]
    assert "x-client-feature-id" not in headers
    assert "x-b3-traceid" not in headers


def test_get_feature_id_and_trace_id_from_env(monkeypatch):
    """The optional getters return the env value, or None when unset."""
    client = AgentforceRelayGatewayClient()
    monkeypatch.delenv(FEATURE_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(TRACE_ID_ENV_VAR, raising=False)
    assert client._get_feature_id() is None
    assert client._get_trace_id() is None

    monkeypatch.setenv(FEATURE_ID_ENV_VAR, "feat-1")
    monkeypatch.setenv(TRACE_ID_ENV_VAR, "trace-1")
    assert client._get_feature_id() == "feat-1"
    assert client._get_trace_id() == "trace-1"


def test_relay_post_raises_when_app_context_unset(monkeypatch):
    """_post raises RuntimeError when SFDC_APP_CONTEXT is not set."""
    monkeypatch.setenv(ORG_JWT_ENV_VAR, "env-jwt")
    monkeypatch.setenv(CORE_TENANT_ID_ENV_VAR, VALID_TENANT)
    monkeypatch.setenv(USER_ID_ENV_VAR, VALID_USER_ID)
    # No BYOC_PROXY_URL: the URL is derived from the tenant id (fallback path).
    monkeypatch.delenv(PROXY_URL_ENV_VAR, raising=False)
    monkeypatch.delenv("SFDC_APP_CONTEXT", raising=False)
    _capture_http(monkeypatch, response_payload={"body": {}, "requestId": "r", "traceId": "t"})

    with pytest.raises(RuntimeError, match="SFDC_APP_CONTEXT"):
        AgentforceRelayGatewayClient().call_llm_generations({"prompt": "hi"})


def test_relay_raises_when_tenant_id_unset(monkeypatch):
    """_relay raises RuntimeError when SFDC_CORE_TENANT_ID is not set."""
    monkeypatch.setenv(ORG_JWT_ENV_VAR, "env-jwt")
    monkeypatch.setenv(USER_ID_ENV_VAR, VALID_USER_ID)
    monkeypatch.delenv(CORE_TENANT_ID_ENV_VAR, raising=False)

    with pytest.raises(RuntimeError, match=CORE_TENANT_ID_ENV_VAR):
        AgentforceRelayGatewayClient().call_llm_generations({"prompt": "hi"})


def test_relay_raises_when_user_id_unset(monkeypatch):
    """_post raises RuntimeError when SFDC_USER_ID is not set."""
    monkeypatch.setenv(ORG_JWT_ENV_VAR, "env-jwt")
    monkeypatch.setenv(CORE_TENANT_ID_ENV_VAR, VALID_TENANT)
    # No BYOC_PROXY_URL: the URL is derived from the tenant id (fallback path).
    monkeypatch.delenv(PROXY_URL_ENV_VAR, raising=False)
    monkeypatch.setenv("SFDC_APP_CONTEXT", "MyApp")
    monkeypatch.delenv(USER_ID_ENV_VAR, raising=False)

    with pytest.raises(RuntimeError, match=USER_ID_ENV_VAR):
        AgentforceRelayGatewayClient().call_llm_generations({"prompt": "hi"})


def test_get_tenant_id_from_env(monkeypatch):
    monkeypatch.setenv(CORE_TENANT_ID_ENV_VAR, VALID_TENANT)
    assert AgentforceRelayGatewayClient()._get_tenant_id() == VALID_TENANT


def test_get_user_id_from_env(monkeypatch):
    monkeypatch.setenv(USER_ID_ENV_VAR, VALID_USER_ID)
    assert AgentforceRelayGatewayClient()._get_user_id() == VALID_USER_ID


def test_client_delegates_to_runtime_gateway(monkeypatch):
    """Client.call_llm_generations delegates to the runtime's relay client."""
    monkeypatch.setenv("AGENTFORCE_BYOC_MOCK", "1")
    monkeypatch.setenv(ORG_JWT_ENV_VAR, "env-jwt")
    monkeypatch.setenv(CORE_TENANT_ID_ENV_VAR, VALID_TENANT)
    monkeypatch.setenv(USER_ID_ENV_VAR, VALID_USER_ID)
    client = get_client()
    captured = _capture_post(client.runtime.relay_gateway_client)

    client.call_llm_generations({"prompt": "hi"})

    assert captured["function"] == "llm"
    assert captured["body"]["function"] == "llm"


# ---------------------------------------------------------------------------
# Deploy client (transport mocked)
# ---------------------------------------------------------------------------


def _capture_http(monkeypatch, status=200, response_payload=b""):
    """Patch _http.request; capture each (method, url, headers, body) call."""
    import json as _json

    from agentforce_byoc import _http

    calls = []
    payload = response_payload
    if not isinstance(payload, (bytes, bytearray)):
        payload = _json.dumps(payload).encode("utf-8")

    def fake_request(method, url, *, headers, body=None, timeout=None):
        calls.append({"method": method, "url": url, "headers": headers, "body": body})
        return status, payload

    monkeypatch.setattr(_http, "request", fake_request)
    return calls


def test_request_presigned_upload(monkeypatch):
    from agentforce_byoc import deploy_client

    calls = _capture_http(
        monkeypatch,
        response_payload={"uploadUrl": "https://s3.example/put", "s3Key": "k"},
    )

    result = deploy_client.request_presigned_upload(
        base_url="https://api.salesforce.com",
        tenant_id=VALID_TENANT,
        org_jwt="jwt-123",
        user_id=VALID_USER_ID,
        app_context=VALID_APP_CONTEXT,
        package_name="pkg",
        version="1.0",
        package_size=2048,
        entry_points=["main.py"],
        max_live_duration_s=300,
    )

    assert result["uploadUrl"] == "https://s3.example/put"
    call = calls[0]
    assert call["method"] == "POST"
    # Register + presign is one call against /byoc/upload/request.
    assert call["url"] == "https://api.salesforce.com/byoc/upload/request"
    assert call["headers"]["Authorization"] == "Bearer jwt-123"
    # The tenant header MUST be lowercase (case-sensitive on the server).
    assert call["headers"]["x-sfdc-core-tenant-id"] == VALID_TENANT
    # Deploy identity headers, matching the relay path.
    assert call["headers"]["x-sfdc-user-id"] == VALID_USER_ID
    assert call["headers"]["x-sfdc-app-context"] == VALID_APP_CONTEXT
    import json as _json

    # Body now carries the metadata the proxy registers up front.
    assert _json.loads(call["body"].decode()) == {
        "packageName": "pkg",
        "version": "1.0",
        "packageSize": 2048,
        "entryPoints": ["main.py"],
        "maxLiveDurationS": 300,
    }


def test_upload_package_uses_gzip_content_type(monkeypatch, tmp_path):
    from agentforce_byoc import deploy_client

    calls = _capture_http(monkeypatch)
    archive = tmp_path / "pkg.tar.gz"
    archive.write_bytes(b"\x1f\x8b fake gzip bytes")

    deploy_client.upload_package("https://s3.example/put?sig=abc", archive)

    call = calls[0]
    assert call["method"] == "PUT"
    assert call["url"] == "https://s3.example/put?sig=abc"
    assert call["headers"]["Content-Type"] == "application/gzip"
    assert call["body"] == b"\x1f\x8b fake gzip bytes"
    # No auth on the presigned PUT.
    assert "Authorization" not in call["headers"]


def test_get_upload_status(monkeypatch):
    from agentforce_byoc import deploy_client

    calls = _capture_http(
        monkeypatch,
        response_payload={
            "registrationStatus": "registered",
            "uploadStatus": "uploaded",
            "s3Key": "k",
        },
    )

    result = deploy_client.get_upload_status(
        base_url="https://api.salesforce.com",
        tenant_id=VALID_TENANT,
        org_jwt="jwt-123",
        user_id=VALID_USER_ID,
        app_context=VALID_APP_CONTEXT,
        package_name="pkg",
        version="1.0",
    )

    assert result["registrationStatus"] == "registered"
    assert result["uploadStatus"] == "uploaded"
    call = calls[0]
    # Read-only poll: GET with query params, no body.
    assert call["method"] == "GET"
    expected_url = "https://api.salesforce.com/byoc/upload/status?packageName=pkg&version=1.0"
    assert call["url"] == expected_url
    assert call["body"] is None
    assert call["headers"]["Authorization"] == "Bearer jwt-123"
    assert call["headers"]["x-sfdc-core-tenant-id"] == VALID_TENANT
    # Deploy identity headers, matching the relay path.
    assert call["headers"]["x-sfdc-user-id"] == VALID_USER_ID
    assert call["headers"]["x-sfdc-app-context"] == VALID_APP_CONTEXT


def test_deploy_client_raises_on_http_error(monkeypatch):
    from agentforce_byoc import deploy_client

    _capture_http(monkeypatch, status=500, response_payload=b"Server Error")

    with pytest.raises(RuntimeError):
        deploy_client.request_presigned_upload(
            base_url="https://api.salesforce.com",
            tenant_id=VALID_TENANT,
            org_jwt="jwt-123",
            user_id=VALID_USER_ID,
            app_context=VALID_APP_CONTEXT,
            package_name="pkg",
            version="1.0",
            package_size=2048,
            entry_points=["main.py"],
            max_live_duration_s=300,
        )


def _call_get_upload_status():
    from agentforce_byoc import deploy_client

    return deploy_client.get_upload_status(
        base_url="https://api.salesforce.com",
        tenant_id=VALID_TENANT,
        org_jwt="jwt-123",
        user_id=VALID_USER_ID,
        app_context=VALID_APP_CONTEXT,
        package_name="pkg",
        version="1.0",
    )


def test_get_upload_status_raises_on_http_error(monkeypatch):
    """GET status path surfaces a non-2xx as RuntimeError."""
    _capture_http(monkeypatch, status=404, response_payload=b"Not Found")
    with pytest.raises(RuntimeError, match="failed with status 404"):
        _call_get_upload_status()


def test_get_upload_status_raises_on_transport_error(monkeypatch):
    """An OSError from the transport becomes a RuntimeError."""
    from agentforce_byoc import _http

    def boom(method, url, *, headers, body=None, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(_http, "request", boom)
    with pytest.raises(RuntimeError, match="failed"):
        _call_get_upload_status()


def test_get_upload_status_raises_on_non_json(monkeypatch):
    """A 200 with a non-JSON body becomes a RuntimeError."""
    _capture_http(monkeypatch, status=200, response_payload=b"not json{")
    with pytest.raises(RuntimeError, match="non-JSON response"):
        _call_get_upload_status()


def test_upload_package_raises_on_http_error(monkeypatch, tmp_path):
    """The presigned PUT surfaces a non-2xx (e.g. bad signature) as RuntimeError."""
    from agentforce_byoc import deploy_client

    _capture_http(monkeypatch, status=403, response_payload=b"AccessDenied")
    archive = tmp_path / "pkg.tar.gz"
    archive.write_bytes(b"\x1f\x8b bytes")
    with pytest.raises(RuntimeError, match="failed with status 403"):
        deploy_client.upload_package("https://s3.example/put?sig=abc", archive)


def test_upload_package_raises_on_transport_error(monkeypatch, tmp_path):
    """An OSError during the PUT becomes a RuntimeError."""
    from agentforce_byoc import _http, deploy_client

    def boom(method, url, *, headers, body=None, timeout=None):
        raise OSError("broken pipe")

    monkeypatch.setattr(_http, "request", boom)
    archive = tmp_path / "pkg.tar.gz"
    archive.write_bytes(b"\x1f\x8b bytes")
    with pytest.raises(RuntimeError, match="Upload to presigned URL failed"):
        deploy_client.upload_package("https://s3.example/put?sig=abc", archive)


# ---------------------------------------------------------------------------
# HTTP transport: header casing preserved verbatim (regression guard)
# ---------------------------------------------------------------------------


def test_http_preserves_lowercase_header_casing():
    """_http must send x-sfdc-core-tenant-id verbatim, not title-cased.

    SFAP / the BYOC proxy match this header case-sensitively; urllib would
    title-case it to X-Sfdc-Core-Tenant-Id and the server would drop it.
    """
    import http.server
    import threading

    from agentforce_byoc import _http

    captured = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            captured["names"] = list(self.headers.keys())
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        status, _ = _http.post_json(
            f"http://127.0.0.1:{port}/byoc/service",
            {"function": "llm", "parameter": {}},
            {"x-sfdc-core-tenant-id": "core/instance-core4/00D"},
        )
    finally:
        srv.shutdown()

    assert status == 200
    assert "x-sfdc-core-tenant-id" in captured["names"]
    assert "X-Sfdc-Core-Tenant-Id" not in captured["names"]
