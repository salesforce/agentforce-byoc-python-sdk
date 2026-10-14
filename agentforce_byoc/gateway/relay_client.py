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

"""Agentforce Relay gateway client."""

import json
import os
from typing import Any, Dict, Optional, cast

from agentforce_byoc import _http
from agentforce_byoc.gateway.base import BaseRelayGatewayClient
from agentforce_byoc.logging import get_logger

logger = get_logger(__name__)

# Environment variable carrying the org JWT, injected into the managed sandbox
# by the Agentforce runtime.
ORG_JWT_ENV_VAR = "ORG_JWT_TOKEN"

# Environment variable carrying the originating invoke's app context, injected
# into the managed sandbox by the Agentforce runtime. The Relay API requires the
# x-sfdc-app-context header (400 header_invalid if missing); we forward this
# value verbatim.
APP_CONTEXT_ENV_VAR = "SFDC_APP_CONTEXT"

# Environment variable carrying the caller's core tenant id
# (``core/<instance>-<fd>/<org-id>``), injected into the managed sandbox by the
# Agentforce runtime. It is forwarded as the x-sfdc-core-tenant-id header, so
# callers no longer thread the tenant id through each relay call.
CORE_TENANT_ID_ENV_VAR = "SFDC_CORE_TENANT_ID"

# Environment variable carrying the caller's user id, injected into the managed
# sandbox by the Agentforce runtime. Forwarded as the x-sfdc-user-id header.
USER_ID_ENV_VAR = "SFDC_USER_ID"

# Environment variable carrying the client feature id, injected into the managed
# sandbox by the Agentforce runtime. Forwarded as the x-client-feature-id header
# so the LLM Gateway can attribute the call to a feature (used for billing).
# OPTIONAL: when unset, the header is simply not sent.
FEATURE_ID_ENV_VAR = "SFDC_FEATURE_ID"

# Environment variable carrying the caller's B3 trace id, injected into the
# managed sandbox by the Agentforce runtime. Forwarded as the x-b3-traceid header
# to propagate the distributed trace. OPTIONAL: when unset, the header is not sent.
TRACE_ID_ENV_VAR = "SFDC_TRACE_ID"

# Relay function identifiers understood by the Relay API.
RELAY_FUNCTION_LLM = "llm"
RELAY_FUNCTION_LLM_CHAT = "llm_chat"

# Environment variable overriding the production Agentforce BYOC API URL. It
# takes one of two forms (see :func:`resolve_relay_url`):
# - the full relay URL (``<base>/byoc/service``), as the Agentforce runtime
#   injects it into the managed sandbox — used as-is by the relay;
# - a base host (e.g. ``https://<env>.api.salesforce.com``), as exported locally
#   for the deploy CLI, which appends its own ``/byoc/upload/...`` path (see
#   :func:`resolve_sfap_base_url`) — the relay appends ``/byoc/service``.
PROXY_URL_ENV_VAR = "BYOC_PROXY_URL"

# Relay endpoint path, appended to the base URL unless it is already present.
_RELAY_PATH = "/byoc/service"

# Default Agentforce BYOC API base URL, used when BYOC_PROXY_URL is not set.
# Production is the only public environment, so it is the default; internal
# developers targeting a pre-production environment point BYOC_PROXY_URL at that
# environment's host instead.
_DEFAULT_SFAP_BASE_URL = "https://api.salesforce.com"

# Relay timeout (seconds) for the outbound POST.
_RELAY_TIMEOUT_S = 60


def resolve_sfap_base_url(tenant_id: str) -> str:
    """
    Resolve the Agentforce BYOC API **base** URL (no endpoint path appended).

    Prefers the ``BYOC_PROXY_URL`` environment variable: when set, it is
    returned verbatim (minus any trailing slash) and the tenant id is ignored.
    Otherwise returns the production default (``https://api.salesforce.com``);
    internal developers targeting a pre-production environment set
    ``BYOC_PROXY_URL`` to that environment's host.

    This returns only the base (e.g. ``https://api.salesforce.com``); the
    caller appends its own endpoint path. The deploy CLI uses it that way
    (``<base>/byoc/upload/request`` etc.), and :func:`resolve_relay_url` appends
    ``/byoc/service``.

    Tenant ids follow ``core/<instance>[-<fd>]/<org-id>`` (e.g.
    ``core/exampleInstance/00Dxx...``). The tenant id is validated for shape
    because it is forwarded as the ``x-sfdc-core-tenant-id`` header, but it no
    longer selects the host.

    Args:
        tenant_id: The core tenant id (validated for shape when
            ``BYOC_PROXY_URL`` is unset; not used to select the host).

    Returns:
        The base URL (no trailing slash, no endpoint path).

    Raises:
        ValueError: If ``BYOC_PROXY_URL`` is unset and the tenant id is
            malformed.
    """
    proxy_url = os.getenv(PROXY_URL_ENV_VAR)
    if proxy_url:
        return proxy_url.rstrip("/")

    if not tenant_id or not isinstance(tenant_id, str):
        raise ValueError(f"Invalid tenant id: {tenant_id!r}")

    parts = tenant_id.split("/")
    if len(parts) != 3 or parts[0] != "core" or not parts[1] or not parts[2]:
        raise ValueError(
            f"Malformed tenant id {tenant_id!r}; expected " "'core/<instance>-<fd>/<org-id>'."
        )

    return _DEFAULT_SFAP_BASE_URL


def resolve_relay_url(tenant_id: str) -> str:
    """
    Resolve the full Relay API endpoint URL (``.../byoc/service``).

    The URL comes from :func:`resolve_sfap_base_url` — ``BYOC_PROXY_URL`` when
    set, else the production default:

    - If it already ends in ``/byoc/service`` (the Agentforce runtime injects
      ``BYOC_PROXY_URL`` into the managed sandbox as the full relay URL), it is
      used as-is. Appending again would produce
      ``.../byoc/service/byoc/service`` and a 404.
    - Otherwise it is a base host (the production default, or a locally
      exported ``BYOC_PROXY_URL`` — the same value the deploy CLI uses) and
      ``/byoc/service`` is appended.

    Args:
        tenant_id: The core tenant id (validated for shape on the default path).

    Returns:
        The full relay endpoint URL (no trailing slash).

    Raises:
        ValueError: If ``BYOC_PROXY_URL`` is unset and the tenant id is
            malformed.
    """
    url = resolve_sfap_base_url(tenant_id)
    if url.endswith(_RELAY_PATH):
        return url
    return f"{url}{_RELAY_PATH}"


class AgentforceRelayGatewayClient(BaseRelayGatewayClient):
    """
    Relay gateway client for the Agentforce BYOC runtime.

    Used when running in the managed sandbox. The org JWT, tenant id, user id,
    and app context are all read from environment variables injected into the
    managed sandbox (``ORG_JWT_TOKEN``, ``SFDC_CORE_TENANT_ID``, ``SFDC_USER_ID``,
    ``SFDC_APP_CONTEXT``); the optional client feature id and trace id come from
    ``SFDC_FEATURE_ID`` / ``SFDC_TRACE_ID`` when injected. The Relay API endpoint
    is resolved by :func:`resolve_relay_url`: ``BYOC_PROXY_URL`` as-is when it
    already ends in ``/byoc/service`` (as the runtime injects it), otherwise
    ``/byoc/service`` appended to the ``BYOC_PROXY_URL`` base host or the
    production default.

    This is the single shared client for all Relay functions. To add a new
    relay function, add a thin method that calls :meth:`_relay` with the
    function name (and a constant for it above).
    """

    def call_llm_generations(self, parameter: Dict[str, Any]) -> Dict[str, Any]:
        return self._relay(RELAY_FUNCTION_LLM, parameter)

    def call_llm_chat_generations(self, parameter: Dict[str, Any]) -> Dict[str, Any]:
        return self._relay(RELAY_FUNCTION_LLM_CHAT, parameter)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _get_org_jwt(self) -> str:
        """
        Resolve the org JWT.

        Reads ``ORG_JWT_TOKEN`` from the environment (injected by the
        Agentforce runtime into the managed sandbox).

        Raises:
            RuntimeError: If the variable is not set.
        """
        org_jwt = os.getenv(ORG_JWT_ENV_VAR)
        if not org_jwt:
            raise RuntimeError(
                f"{ORG_JWT_ENV_VAR} environment variable is not set. "
                "It is injected by the Agentforce runtime; for local testing "
                f"export {ORG_JWT_ENV_VAR}."
            )
        return org_jwt

    def _get_tenant_id(self) -> str:
        """
        Resolve the core tenant id.

        Reads ``SFDC_CORE_TENANT_ID`` from the environment (injected by the
        Agentforce runtime). It is forwarded as the ``x-sfdc-core-tenant-id``
        header.

        Raises:
            RuntimeError: If the variable is not set.
        """
        tenant_id = os.getenv(CORE_TENANT_ID_ENV_VAR)
        if not tenant_id:
            raise RuntimeError(
                f"{CORE_TENANT_ID_ENV_VAR} environment variable is not set. "
                "It is injected by the Agentforce runtime; for local testing "
                f"export {CORE_TENANT_ID_ENV_VAR}."
            )
        return tenant_id

    def _get_user_id(self) -> str:
        """
        Resolve the caller's user id.

        Reads ``SFDC_USER_ID`` from the environment (injected by the Agentforce
        runtime) and forwards it as the ``x-sfdc-user-id`` header.

        Raises:
            RuntimeError: If the variable is not set.
        """
        user_id = os.getenv(USER_ID_ENV_VAR)
        if not user_id:
            raise RuntimeError(
                f"{USER_ID_ENV_VAR} environment variable is not set. "
                "It is injected by the Agentforce runtime; for local testing "
                f"export {USER_ID_ENV_VAR}."
            )
        return user_id

    def _get_app_context(self) -> str:
        """
        Resolve the invoke's app context.

        Reads ``SFDC_APP_CONTEXT`` from the environment (injected by the
        Agentforce runtime) and forwards it as the ``x-sfdc-app-context``
        header. The relay endpoint requires this header (400
        ``header_invalid`` without it).

        Raises:
            RuntimeError: If the variable is not set.
        """
        app_context = os.getenv(APP_CONTEXT_ENV_VAR)
        if not app_context:
            raise RuntimeError(
                f"{APP_CONTEXT_ENV_VAR} environment variable is not set. "
                "It is injected by the Agentforce runtime; for local testing "
                f"export {APP_CONTEXT_ENV_VAR}."
            )
        return app_context

    def _get_feature_id(self) -> Optional[str]:
        """
        Resolve the optional client feature id.

        Reads ``SFDC_FEATURE_ID`` from the environment (injected by the
        Agentforce runtime) to be forwarded as the ``x-client-feature-id``
        header, which the LLM Gateway uses to attribute the call to a feature.

        Unlike the mandatory identity vars, this is OPTIONAL: returns ``None``
        when unset (or blank) so the caller omits the header entirely.
        """
        return os.getenv(FEATURE_ID_ENV_VAR) or None

    def _get_trace_id(self) -> Optional[str]:
        """
        Resolve the optional B3 trace id.

        Reads ``SFDC_TRACE_ID`` from the environment (injected by the
        Agentforce runtime) to be forwarded as the ``x-b3-traceid`` header,
        propagating the distributed trace across the relay.

        Unlike the mandatory identity vars, this is OPTIONAL: returns ``None``
        when unset (or blank) so the caller omits the header entirely.
        """
        return os.getenv(TRACE_ID_ENV_VAR) or None

    def _build_request_body(self, function: str, parameter: Dict[str, Any]) -> Dict[str, Any]:
        """
        Construct the Relay request body.

        The Relay API (``RelayRequest``) accepts only ``function`` and
        ``parameter``. The tenant and org JWT travel as headers, not in the
        body (see :meth:`_post`).
        """
        return {
            "function": function,
            "parameter": parameter,
        }

    def _post(
        self,
        function: str,
        body: Dict[str, Any],
        org_jwt: str,
    ) -> Dict[str, Any]:
        """
        Resolve the target URL + identity headers and POST the JSON body,
        returning the parsed JSON response.

        The endpoint URL comes from :func:`resolve_relay_url`: ``BYOC_PROXY_URL``
        as-is when it already ends in ``/byoc/service``, otherwise
        ``/byoc/service`` appended to the base host (``BYOC_PROXY_URL`` or the
        production default). The tenant id is
        sent as the ``x-sfdc-core-tenant-id`` header. The org JWT
        is sent as a bearer token; the app context and user id are resolved
        from the injected environment and sent as the ``x-sfdc-app-context`` /
        ``x-sfdc-user-id`` headers.

        Two OPTIONAL client-context headers are forwarded only when their env
        vars are set: ``x-client-feature-id`` (from ``SFDC_FEATURE_ID``, used by
        the LLM Gateway for feature attribution) and ``x-b3-traceid`` (from
        ``SFDC_TRACE_ID``, for distributed-trace propagation). When either env
        var is unset the corresponding header is omitted entirely.

        Args:
            function: The relay function name (used only for the log line).
            body: The relay request body (``function`` + ``parameter``).
            org_jwt: The org JWT bearer token.

        Raises:
            RuntimeError: On transport error, non-JSON response, or if any of
                the injected identity env vars (tenant id, app context, user
                id) is unset.
        """
        tenant_id = self._get_tenant_id()
        url = resolve_relay_url(tenant_id)
        # The org JWT is sent as a bearer token; the tenant id also travels as
        # the x-sfdc-core-tenant-id header. A 400 "x-sfdc-core-tenant-id header
        # is required" indicates the JWT was rejected, not a missing header here.
        # x-sfdc-app-context is mandatory on the relay endpoint (400
        # header_invalid without it); forward the injected value.
        headers = {
            "Authorization": f"Bearer {org_jwt}",
            "x-sfdc-core-tenant-id": tenant_id,
            "x-sfdc-app-context": self._get_app_context(),
            "x-sfdc-user-id": self._get_user_id(),
        }
        # Optional client-context headers: forwarded only when the injected env
        # var is present, so agents that don't set them are unaffected.
        feature_id = self._get_feature_id()
        if feature_id:
            headers["x-client-feature-id"] = feature_id
        trace_id = self._get_trace_id()
        if trace_id:
            headers["x-b3-traceid"] = trace_id
        logger.info(
            "Relaying %s for tenant=%s to %s",
            function,
            tenant_id,
            url,
        )
        try:
            status, raw = _http.post_json(url, body, headers, timeout=_RELAY_TIMEOUT_S)
        except OSError as e:
            raise RuntimeError(f"Relay API call to {url} failed: {e}") from e

        if status >= 400:
            raise RuntimeError(f"Relay API call to {url} failed with status {status}: {raw}")

        try:
            return cast(Dict[str, Any], json.loads(raw))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Relay API at {url} returned a non-JSON response: {raw!r}") from e

    def _relay(self, function: str, parameter: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve the org JWT, build the body, and POST to the Relay API.

        The org JWT is read from the environment; ``_post`` resolves the
        tenant id (for both the endpoint URL and its header), the app context,
        and the user id from the injected environment itself.
        """
        org_jwt = self._get_org_jwt()
        body = self._build_request_body(function, parameter)
        return self._post(function, body, org_jwt)
