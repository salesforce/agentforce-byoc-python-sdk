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

"""Mock Relay gateway client for local development."""

import os
from typing import Optional

from agentforce_byoc.gateway.relay_client import ORG_JWT_ENV_VAR, AgentforceRelayGatewayClient
from agentforce_byoc.logging import get_logger

logger = get_logger(__name__)


class MockRelayGatewayClient(AgentforceRelayGatewayClient):
    """
    Relay gateway client for local development outside the managed sandbox.

    Behaves exactly like :class:`AgentforceRelayGatewayClient` — same URL
    resolution, request shape, and transport — except the org JWT is supplied
    by the SDK author rather than injected by the runtime. The JWT is taken
    from the ``org_jwt`` constructor argument, falling back to the
    ``ORG_JWT_TOKEN`` environment variable.
    """

    def __init__(self, org_jwt: Optional[str] = None):
        self._org_jwt = org_jwt

    def _get_org_jwt(self) -> str:
        """
        Resolve the org JWT from the constructor arg or ``ORG_JWT_TOKEN``.

        Raises:
            RuntimeError: If neither source provides a JWT.
        """
        org_jwt = self._org_jwt or os.getenv(ORG_JWT_ENV_VAR)
        if not org_jwt:
            raise RuntimeError(
                f"No org JWT supplied for mock mode. Pass org_jwt=... or "
                f"export {ORG_JWT_ENV_VAR}."
            )
        return org_jwt
