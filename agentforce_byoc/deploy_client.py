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

"""HTTP client for the Agentforce BYOC deploy/upload API.

Implements the two-step package upload against the Agentforce BYOC platform:

1. ``POST <base>/byoc/upload/request`` to register package metadata AND obtain a
   presigned upload URL in one call. The body carries ``packageName``,
   ``version``, ``packageSize``, ``entryPoints``, and ``maxLiveDurationS``; the
   response returns the presigned ``uploadUrl``.
2. ``PUT`` the package archive to that presigned URL.

Deployment status can then be polled read-only via
``GET <base>/byoc/upload/status?packageName=&version=``, which reports
``registrationStatus`` (is the package registered) and ``uploadStatus`` (has the
archive been uploaded). That endpoint never writes — registration happens in
step 1.

The base URL is resolved by
:func:`agentforce_byoc.gateway.relay_client.resolve_sfap_base_url` — from the
``BYOC_PROXY_URL`` environment variable when set, else the production default.
Auth is sent as ``Authorization: Bearer <org-jwt>`` plus the
``x-sfdc-core-tenant-id``, ``x-sfdc-user-id``, and ``x-sfdc-app-context``
headers.

Uses only the Python standard library so nothing extra is bundled into a BYOC
package.
"""

import json
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, cast

from agentforce_byoc import _http
from agentforce_byoc.logging import get_logger

logger = get_logger(__name__)

# The presigned URL is signed for ContentType "application/gzip". The PUT must
# send exactly this Content-Type or the upload is rejected as a signature
# mismatch.
_PACKAGE_CONTENT_TYPE = "application/gzip"

# Timeout (seconds) for API calls and the package upload PUT.
_DEPLOY_TIMEOUT_S = 120


def _post_json(
    url: str,
    body: Dict[str, Any],
    org_jwt: str,
    tenant_id: str,
    user_id: str,
    app_context: str,
) -> Dict[str, Any]:
    """
    POST a JSON body to a BYOC API endpoint and parse the response.

    Sends the org JWT as a bearer token plus the tenant id, user id, and app
    context as the ``x-sfdc-core-tenant-id`` / ``x-sfdc-user-id`` /
    ``x-sfdc-app-context`` headers.

    Raises:
        RuntimeError: On HTTP error, transport error, or a non-JSON response.
    """
    # The org JWT is sent as a bearer token; the tenant id also travels as the
    # x-sfdc-core-tenant-id header. A 400 "x-sfdc-core-tenant-id header is
    # required" indicates the JWT was rejected, not a missing header here. The
    # user id and app context identify who is deploying, matching the relay path.
    headers = {
        "Authorization": f"Bearer {org_jwt}",
        "x-sfdc-core-tenant-id": tenant_id,
        "x-sfdc-user-id": user_id,
        "x-sfdc-app-context": app_context,
    }
    try:
        status, raw = _http.post_json(url, body, headers, timeout=_DEPLOY_TIMEOUT_S)
    except OSError as e:
        raise RuntimeError(f"BYOC API call to {url} failed: {e}") from e

    # Surface the BYOC API response (status + body) so callers can see exactly
    # what the platform returned.
    logger.info("BYOC API %s -> status=%s body=%s", url, status, raw)

    if status >= 400:
        raise RuntimeError(f"BYOC API call to {url} failed with status {status}: {raw}")

    try:
        return cast(Dict[str, Any], json.loads(raw))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"BYOC API at {url} returned a non-JSON response: {raw!r}") from e


def _get_json(
    url: str,
    org_jwt: str,
    tenant_id: str,
    user_id: str,
    app_context: str,
) -> Dict[str, Any]:
    """
    GET a BYOC API endpoint and parse the JSON response.

    Sends the same identity headers as :func:`_post_json`. Used for the
    read-only ``GET /byoc/upload/status`` poll, which takes its parameters in
    the query string and has no request body.

    Raises:
        RuntimeError: On HTTP error, transport error, or a non-JSON response.
    """
    headers = {
        "Authorization": f"Bearer {org_jwt}",
        "x-sfdc-core-tenant-id": tenant_id,
        "x-sfdc-user-id": user_id,
        "x-sfdc-app-context": app_context,
    }
    try:
        status, raw = _http.request("GET", url, headers=headers, timeout=_DEPLOY_TIMEOUT_S)
    except OSError as e:
        raise RuntimeError(f"BYOC API call to {url} failed: {e}") from e

    body_text = raw.decode("utf-8", errors="replace")
    logger.info("BYOC API %s -> status=%s body=%s", url, status, body_text)

    if status >= 400:
        raise RuntimeError(f"BYOC API call to {url} failed with status {status}: {body_text}")

    try:
        return cast(Dict[str, Any], json.loads(body_text))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"BYOC API at {url} returned a non-JSON response: {body_text!r}") from e


def _put_file(url: str, file_path: Path, content_type: str) -> None:
    """
    PUT a file's bytes to a (presigned) URL.

    No auth header is added: the presigned URL carries its own signature.

    Raises:
        RuntimeError: On HTTP error or transport error.
    """
    data = file_path.read_bytes()
    try:
        status, raw = _http.request(
            "PUT",
            url,
            headers={"Content-Type": content_type},
            body=data,
            timeout=_DEPLOY_TIMEOUT_S,
        )
    except OSError as e:
        raise RuntimeError(f"Upload to presigned URL failed: {e}") from e

    if status >= 400:
        body_text = raw.decode("utf-8", errors="replace")
        raise RuntimeError(f"Upload to presigned URL failed with status {status}: {body_text}")


def request_presigned_upload(
    base_url: str,
    tenant_id: str,
    org_jwt: str,
    user_id: str,
    app_context: str,
    package_name: str,
    version: str,
    package_size: int,
    entry_points: List[str],
    max_live_duration_s: int,
) -> Dict[str, Any]:
    """
    Step 1: register package metadata and get a presigned upload URL.

    ``POST /byoc/upload/request`` does both in one call: it registers the
    package metadata (``packageSize``, ``entryPoints``, ``maxLiveDurationS``) and
    returns the presigned ``uploadUrl``. The caller then PUTs the archive to that
    URL (see :func:`upload_package`).

    Returns:
        The response ``{uploadUrl, s3Key, tenantId, packageName, version,
        uploadTime, packageSize, entryPoints, maxLiveDurationS, status}``.
    """
    url = f"{base_url}/byoc/upload/request"
    body = {
        "packageName": package_name,
        "version": version,
        "packageSize": package_size,
        "entryPoints": entry_points,
        "maxLiveDurationS": max_live_duration_s,
    }
    logger.info("Registering package + requesting presigned upload URL from %s", url)
    return _post_json(url, body, org_jwt, tenant_id, user_id, app_context)


def upload_package(upload_url: str, file_path: Path) -> None:
    """Step 2: upload the package archive to the presigned URL."""
    logger.info("Uploading %s (%d bytes)", file_path.name, file_path.stat().st_size)
    _put_file(upload_url, file_path, _PACKAGE_CONTENT_TYPE)


def get_upload_status(
    base_url: str,
    tenant_id: str,
    org_jwt: str,
    user_id: str,
    app_context: str,
    package_name: str,
    version: str,
) -> Dict[str, Any]:
    """
    Poll deployment status (read-only).

    Calls ``GET /byoc/upload/status`` with ``packageName`` and ``version`` in the
    query string. The endpoint never writes — registration happens in
    :func:`request_presigned_upload`. It reports both halves of the two-phase
    upload independently:

    - ``registrationStatus``: ``"registered"`` if the package metadata exists,
      else ``"unregistered"``.
    - ``uploadStatus``: ``"uploaded"`` if the archive has been uploaded,
      ``"pending"`` if not, ``"unknown"`` if the check itself failed.

    Returns:
        ``{tenantId, packageName, version, s3Key, registrationStatus,
        uploadStatus, ...}`` (plus ``uploadTime``/``packageSize``/``entryPoints``/
        ``maxLiveDurationS`` when registered).
    """
    query = urllib.parse.urlencode({"packageName": package_name, "version": version})
    url = f"{base_url}/byoc/upload/status?{query}"
    logger.info("Polling upload status from %s", url)
    return _get_json(url, org_jwt, tenant_id, user_id, app_context)
