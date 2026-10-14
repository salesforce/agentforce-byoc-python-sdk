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

"""Base class for relay gateway clients."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseRelayGatewayClient(ABC):
    """
    Abstract base class for Relay gateway clients.

    The Relay gateway routes API calls from BYOC code (running in the managed
    sandbox, which has no direct outbound network) through the Agentforce Relay
    API. Each relay function is exposed as a method.

    Implementations must relay the raw ``parameter`` body through to the
    Relay API unchanged.
    """

    @abstractmethod
    def call_llm_generations(self, parameter: Dict[str, Any]) -> Dict[str, Any]:
        """
        Relay an LLM generations call (Relay function ``llm``).

        The tenant id, user id, and app context are resolved from the
        environment (``SFDC_CORE_TENANT_ID`` / ``SFDC_USER_ID`` /
        ``SFDC_APP_CONTEXT``) injected into the managed sandbox.

        Args:
            parameter: Raw request body, passed through to the Relay API as-is.

        Returns:
            The Relay API response envelope (``{body, requestId, traceId}``).
        """
        ...

    @abstractmethod
    def call_llm_chat_generations(self, parameter: Dict[str, Any]) -> Dict[str, Any]:
        """
        Relay an LLM chat generations call (Relay function ``llm_chat``).

        The tenant id, user id, and app context are resolved from the
        environment (``SFDC_CORE_TENANT_ID`` / ``SFDC_USER_ID`` /
        ``SFDC_APP_CONTEXT``) injected into the managed sandbox.

        Args:
            parameter: Raw request body, passed through to the Relay API as-is.

        Returns:
            The Relay API response envelope (``{body, requestId, traceId}``).
        """
        ...
