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

"""Base class for runtime providers."""

from abc import ABC, abstractmethod

from agentforce_byoc.gateway.base import BaseRelayGatewayClient


class BaseRuntimeProvider(ABC):
    """
    Abstract base class for runtime environment providers.

    Each runtime provider encapsulates the configuration and gateway clients
    for a specific execution environment (Agentforce runtime or local mock).
    """

    def __init__(self):
        """Initialize runtime provider."""
        self._relay_gateway_client: BaseRelayGatewayClient = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the runtime provider name."""
        pass

    @property
    def relay_gateway_client(self) -> BaseRelayGatewayClient:
        """
        Get the Relay gateway client for this runtime.

        Returns:
            Configured Relay gateway client instance

        Raises:
            RuntimeError: If the Relay gateway client is not configured
        """
        if self._relay_gateway_client is None:
            raise RuntimeError(f"Relay gateway client not configured for runtime: {self.name}")
        return self._relay_gateway_client
