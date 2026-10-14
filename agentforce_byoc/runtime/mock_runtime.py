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

"""Mock runtime provider for local testing."""

from agentforce_byoc.gateway.mock_relay_client import MockRelayGatewayClient
from agentforce_byoc.runtime.base import BaseRuntimeProvider


class MockRuntimeProvider(BaseRuntimeProvider):
    """
    Mock runtime provider for local development outside the managed sandbox.

    Wires up the :class:`MockRelayGatewayClient`, which behaves like the
    Agentforce client but takes the org JWT from the SDK author (constructor
    arg or the ``ORG_JWT_TOKEN`` env var).

    Example:
        This provider is selected when the AGENTFORCE_BYOC_MOCK env var is set:

        >>> import os
        >>> os.environ["AGENTFORCE_BYOC_MOCK"] = "1"
        >>> from agentforce_byoc import get_client
        >>> client = get_client()
        >>> client.call_llm_generations(
        ...     parameter={"prompt": "What is AI?"},
        ... )
    """

    def __init__(self):
        """Initialize mock runtime provider."""
        super().__init__()
        self._relay_gateway_client = MockRelayGatewayClient()

    @property
    def name(self) -> str:
        """Return runtime name."""
        return "mock"
