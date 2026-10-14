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

"""Client for Agentforce BYOC SDK."""

import os
from typing import Any, Dict, Optional

from agentforce_byoc.logging import get_logger
from agentforce_byoc.runtime.base import BaseRuntimeProvider

logger = get_logger(__name__)


def _is_mock_mode() -> bool:
    """Return True if mock mode is enabled via AGENTFORCE_BYOC_MOCK."""
    return os.getenv("AGENTFORCE_BYOC_MOCK", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _select_runtime_provider() -> BaseRuntimeProvider:
    """
    Select the runtime provider.

    Mock mode (AGENTFORCE_BYOC_MOCK truthy) uses the mock provider; otherwise
    the Agentforce BYOC runtime is used (default).
    """
    if _is_mock_mode():
        logger.info("AGENTFORCE_BYOC_MOCK set - using MOCK runtime")
        from agentforce_byoc.runtime.mock_runtime import MockRuntimeProvider

        return MockRuntimeProvider()

    from agentforce_byoc.runtime.agentforce_runtime import AgentforceRuntimeProvider

    return AgentforceRuntimeProvider()


class Client:
    """
    Main client for interacting with Agentforce services.

    The Client selects the runtime (Agentforce BYOC by default, or mock when
    AGENTFORCE_BYOC_MOCK is set) and provides a unified interface for relaying
    calls through the Agentforce Relay API.

    Features:
    - Runtime selection via AGENTFORCE_BYOC_MOCK env var
    - Singleton pattern (one instance per application)
    - Relay calls for LLM generations and chat generations

    Example:
        >>> from agentforce_byoc import Client
        >>> client = Client()
        >>> response = client.call_llm_generations(
        ...     parameter={"prompt": "What is AI?"},
        ... )

    Note:
        Typically you don't instantiate Client directly - use Agent base class
        which provides self.client automatically.
    """

    _instance: Optional["Client"] = None
    _runtime_provider: Optional[BaseRuntimeProvider] = None

    def __new__(cls, runtime_provider: Optional[BaseRuntimeProvider] = None):
        """
        Create or return singleton Client instance.

        Args:
            runtime_provider: Optional runtime provider (for testing/advanced use)

        Returns:
            Client singleton instance

        Raises:
            ValueError: If trying to change runtime provider after initialization
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)

            # Select runtime if not provided
            if runtime_provider is None:
                cls._runtime_provider = _select_runtime_provider()
            else:
                cls._runtime_provider = runtime_provider

            logger.info(f"Initialized Client with runtime: {cls._runtime_provider.name}")

        elif runtime_provider is not None and cls._instance is not None:
            raise ValueError(
                "Cannot set runtime_provider after Client is initialized. "
                "Create a new Client by resetting the singleton first."
            )

        return cls._instance

    @classmethod
    def reset(cls):
        """
        Reset the singleton instance.

        Useful for testing when you need to reinitialize with different runtime.

        Example:
            >>> Client.reset()
            >>> client = Client(custom_runtime_provider)
        """
        cls._instance = None
        cls._runtime_provider = None

    @property
    def runtime(self) -> BaseRuntimeProvider:
        """Get the current runtime provider."""
        if self._runtime_provider is None:
            raise RuntimeError("Client is not initialized with a runtime provider.")
        return self._runtime_provider

    def call_llm_generations(self, parameter: Dict[str, Any]) -> Dict[str, Any]:
        """
        Relay an LLM generations call through the Agentforce Relay API.

        The tenant id, user id, and app context are resolved from the
        environment (``SFDC_CORE_TENANT_ID`` / ``SFDC_USER_ID`` /
        ``SFDC_APP_CONTEXT``) injected into the managed sandbox.

        Args:
            parameter: Raw request body, passed through to the Relay API as-is.

        Returns:
            The Relay API response envelope (``{body, requestId, traceId}``).

        Raises:
            RuntimeError: If the Relay API call fails, or the tenant id / user
                id / app context environment variables are not set.
            ValueError: If the tenant id cannot be resolved to an endpoint.
        """
        provider = self.runtime
        logger.debug(
            "Calling Relay (llm)",
            extra={"runtime": provider.name},
        )
        return provider.relay_gateway_client.call_llm_generations(parameter=parameter)

    def call_llm_chat_generations(self, parameter: Dict[str, Any]) -> Dict[str, Any]:
        """
        Relay an LLM chat generations call through the Agentforce Relay API.

        The tenant id, user id, and app context are resolved from the
        environment (``SFDC_CORE_TENANT_ID`` / ``SFDC_USER_ID`` /
        ``SFDC_APP_CONTEXT``) injected into the managed sandbox.

        Args:
            parameter: Raw request body, passed through to the Relay API as-is.

        Returns:
            The Relay API response envelope (``{body, requestId, traceId}``).

        Raises:
            RuntimeError: If the Relay API call fails, or the tenant id / user
                id / app context environment variables are not set.
            ValueError: If the tenant id cannot be resolved to an endpoint.
        """
        provider = self.runtime
        logger.debug(
            "Calling Relay (llm_chat)",
            extra={"runtime": provider.name},
        )
        return provider.relay_gateway_client.call_llm_chat_generations(parameter=parameter)


# ============================================================================
# Functional API
# ============================================================================


def get_client(runtime_provider: Optional[BaseRuntimeProvider] = None) -> Client:
    """
    Get the singleton Client instance (functional API).

    This is the recommended way to access the client in functional-style code.
    The client selects the runtime on first call.

    Args:
        runtime_provider: Optional runtime provider (for testing/advanced use)

    Returns:
        Client singleton instance

    Example:
        >>> from agentforce_byoc import get_client
        >>>
        >>> def function(request: dict) -> dict:
        ...     client = get_client()
        ...     response = client.call_llm_generations(
        ...         parameter={"prompt": request.get("text", "")},
        ...     )
        ...     return {"response": response}

    Runtime Selection:
        - Agentforce BYOC runtime (default)
        - Mock mode: AGENTFORCE_BYOC_MOCK is set (truthy)

    Note:
        The client is a singleton - calling get_client() multiple times
        returns the same instance.
    """
    return Client(runtime_provider=runtime_provider)
