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

"""Agentforce BYOC runtime provider."""

from agentforce_byoc.gateway.relay_client import AgentforceRelayGatewayClient
from agentforce_byoc.logging import get_logger
from agentforce_byoc.runtime.base import BaseRuntimeProvider

logger = get_logger(__name__)


class AgentforceRuntimeProvider(BaseRuntimeProvider):
    """
    Agentforce BYOC runtime provider.

    This is the default runtime, used when running in the managed sandbox. It
    wires up the :class:`AgentforceRelayGatewayClient`, which relays calls
    through the Agentforce Relay API.

    The org JWT is read from the ``ORG_JWT_TOKEN`` environment variable
    injected into the managed sandbox, and the endpoint URL is resolved per call
    from the tenant id.
    """

    def __init__(self):
        """Initialize the Agentforce runtime provider."""
        super().__init__()
        logger.info("Initialized Agentforce BYOC runtime")
        self._relay_gateway_client = AgentforceRelayGatewayClient()

    @property
    def name(self) -> str:
        """Return runtime name."""
        return "agentforce"
