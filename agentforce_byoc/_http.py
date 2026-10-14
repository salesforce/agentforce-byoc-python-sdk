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

"""Internal HTTP helpers (stdlib only).

Small wrapper over ``http.client`` so the relay and deploy clients share one
request path with no third-party dependencies (nothing extra gets bundled into
a BYOC package). It sends outgoing header names verbatim.

Set ``AGENTFORCE_BYOC_DEBUG=1`` to log the outgoing request (method, URL,
headers, and body) and the response. The ``Authorization`` bearer token is
truncated in the log, so debug output never contains the full credential. This
is invaluable when a call fails in a way that looks like a client bug: e.g. a
400 "x-sfdc-core-tenant-id header is required" is usually returned by the
platform when it cannot resolve the tenant from the OrgJWT (expired/unauthorized
token) -- not because the SDK omitted the header. The logged request headers
show exactly which headers left the machine (with the token redacted).
"""

import http.client
import json
import os
import urllib.parse
from typing import Any, Dict, Optional, Tuple

from agentforce_byoc.logging import get_logger

logger = get_logger(__name__)

# Default timeout (seconds) for SDK HTTP calls.
DEFAULT_TIMEOUT_S = 120


def _debug_enabled() -> bool:
    return os.getenv("AGENTFORCE_BYOC_DEBUG", "").strip().lower() in ("1", "true", "yes")


def _redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Copy headers with the bearer token truncated for safe logging."""
    redacted = {}
    for k, v in headers.items():
        if k.lower() == "authorization" and isinstance(v, str):
            # Keep the scheme + first/last few chars so we can spot a bad token.
            redacted[k] = (v[:18] + "...(" + str(len(v)) + " chars)") if len(v) > 24 else v
        else:
            redacted[k] = v
    return redacted


def _connect(parsed: urllib.parse.ParseResult, timeout: int):
    """Open an HTTP(S) connection for a parsed URL."""
    host = parsed.hostname
    if host is None:
        raise ValueError(f"URL has no host: {parsed.geturl()!r}")
    port = parsed.port
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=timeout)
    return http.client.HTTPConnection(host, port, timeout=timeout)


def _path_with_query(parsed: urllib.parse.ParseResult) -> str:
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path


def request(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    body: Optional[bytes] = None,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> Tuple[int, bytes]:
    """
    Send an HTTP request and return the status and raw response body.

    Returns:
        (status_code, response_body_bytes)

    Raises:
        OSError: On connection/transport failure (caller maps to its own error).
    """
    parsed = urllib.parse.urlparse(url)
    debug = _debug_enabled()

    if debug:
        logger.info("[debug] HTTP %s %s", method, url)
        logger.info(
            "[debug] host=%s port=%s scheme=%s", parsed.hostname, parsed.port, parsed.scheme
        )
        logger.info("[debug] request path=%s", _path_with_query(parsed))
        logger.info("[debug] request headers=%s", _redact_headers(headers))
        if body is not None:
            preview = body.decode("utf-8", errors="replace")
            logger.info("[debug] request body=%s", preview)

    conn = _connect(parsed, timeout)
    try:
        conn.request(method, _path_with_query(parsed), body=body, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        raw = resp.read()
        if debug:
            logger.info("[debug] response status=%s", status)
            logger.info("[debug] response headers=%s", dict(resp.getheaders()))
            logger.info("[debug] response body=%s", raw.decode("utf-8", errors="replace"))
        return status, raw
    finally:
        conn.close()


def post_json(
    url: str,
    body: Dict[str, Any],
    headers: Dict[str, str],
    *,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> Tuple[int, str]:
    """
    POST a JSON body. Sets Content-Type and serializes ``body``.

    Returns:
        (status_code, response_text)
    """
    merged = {"Content-Type": "application/json", **headers}
    data = json.dumps(body).encode("utf-8")
    status, raw = request("POST", url, headers=merged, body=data, timeout=timeout)
    return status, raw.decode("utf-8", errors="replace")
