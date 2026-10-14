#!/usr/bin/env python3
# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Example 02: LLM Agent (Functional Style)
========================================

This example demonstrates relaying an LLM generations call through the
Agentforce Relay API using functional style.

Key Concepts:
- Using get_client() to access the client
- Relaying an LLM call with call_llm_generations(parameter)
- Handling the relay response envelope
- Error handling

Note:
    Both runtimes relay to the Agentforce Relay API over the network, so a
    reachable endpoint and a valid org JWT are required. The tenant id, user
    id, and app context are read from the environment (SFDC_CORE_TENANT_ID /
    SFDC_USER_ID / SFDC_APP_CONTEXT), which the runtime injects in the sandbox
    and you export for local runs. Mock mode differs only in that the JWT comes
    from the author (ORG_JWT_TOKEN) rather than being injected by the runtime.

Usage:
    export ORG_JWT_TOKEN=<your-org-jwt>
    export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
    export SFDC_USER_ID=<user-id>
    export SFDC_APP_CONTEXT=<app-context>

    # Mock mode (author supplies the JWT)
    AGENTFORCE_BYOC_MOCK=1 python examples/02_llm_agent.py

    # Agentforce runtime (default; JWT injected by the runtime)
    python examples/02_llm_agent.py
"""

from agentforce_byoc import get_client, get_logger

# Initialize logger
logger = get_logger(__name__)


def function(request: dict) -> dict:
    """
    Generate a response by relaying an LLM call through the Relay API.

    Args:
        request: Must contain:
            - 'prompt': Input text

    Returns:
        Dictionary with the relay response
    """
    # Extract inputs from request
    prompt = request.get("prompt", "")

    if not prompt:
        logger.warning("Empty prompt received")
        return {"status": "error", "error": "Missing 'prompt' in request"}

    logger.info(f"Relaying LLM call with prompt: '{prompt[:50]}...'")

    try:
        # Get client and relay the LLM generations call. `parameter` is the
        # raw request body for the LLM service and is passed through as-is. The
        # tenant id, user id, and app context are resolved from the environment
        # (SFDC_CORE_TENANT_ID / SFDC_USER_ID / SFDC_APP_CONTEXT).
        client = get_client()
        relay_response = client.call_llm_generations(
            parameter={
                "model": "llmgateway__OpenAIGPT35Turbo",
                "prompt": prompt,
                "max_tokens": 150,
            },
        )

        logger.info("Relay response received")

        return {
            "status": "success",
            "prompt": prompt,
            "response": relay_response,
        }

    except Exception as e:
        logger.error(f"Relay call failed: {e}")
        return {"status": "error", "error": str(e), "prompt": prompt}


def main():
    """Run the agent with example prompts."""
    print("=" * 60)
    print("Example 02: LLM Agent (Functional)")
    print("=" * 60)

    # The tenant id, user id, and app context come from the environment
    # (SFDC_CORE_TENANT_ID / SFDC_USER_ID / SFDC_APP_CONTEXT).

    # Test prompts
    test_prompts = [
        "What is artificial intelligence?",
        "Explain quantum computing in simple terms.",
        "Write a haiku about coding.",
    ]

    for i, prompt in enumerate(test_prompts, 1):
        print(f"\n{'─' * 60}")
        print(f"Test Case {i}")
        print(f"{'─' * 60}")
        print(f"Prompt: {prompt}")
        print()

        response = function({"prompt": prompt})

        print(f"Status: {response['status']}")
        if response["status"] == "success":
            print(f"\nResponse:\n{response['response']}")
        else:
            print(f"Error: {response['error']}")

    print(f"\n{'=' * 60}")
    print("✅ Example completed successfully")
    print("=" * 60)
    print("\nNote: Both runtimes relay over the network and need a valid")
    print("ORG_JWT_TOKEN and a reachable endpoint for the tenant.")


if __name__ == "__main__":
    main()
