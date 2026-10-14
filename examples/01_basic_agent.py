#!/usr/bin/env python3
# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Example 01: Basic Agent (Functional Style)
==========================================

This example demonstrates the minimal functional agent implementation.

Key Concepts:
- Simple function that BYOC runtime will call
- Direct functional style - no classes needed
- Return a dictionary response

Usage:
    python examples/01_basic_agent.py
"""

from agentforce_byoc import get_logger

# Initialize logger for this module
logger = get_logger(__name__)


def function(request: dict) -> dict:
    """
    Entry point called by the Agentforce BYOC runtime.

    This is the simplest possible agent - just processes the request
    and returns a response. No LLM calls, no external dependencies.

    Args:
        request: Input data from Agentforce (arbitrary dict structure)

    Returns:
        Dictionary response to be sent back to Agentforce
    """
    logger.info("Processing request", extra={"request_keys": list(request.keys())})

    # Simple echo logic
    message = request.get("message", "No message provided")

    return {"status": "success", "echo": message, "processed": True}


def main():
    """Run the agent with example inputs."""
    print("=" * 60)
    print("Example 01: Basic Agent (Functional)")
    print("=" * 60)

    # Test with different inputs
    test_cases = [
        {"message": "Hello, Agentforce!"},
        {"message": "Test input", "user_id": "12345"},
        {},  # Empty request
    ]

    for i, test_input in enumerate(test_cases, 1):
        print(f"\nTest Case {i}:")
        print(f"  Input:  {test_input}")

        response = function(test_input)

        print(f"  Output: {response}")

    print("\n" + "=" * 60)
    print("✅ Example completed successfully")
    print("=" * 60)


if __name__ == "__main__":
    main()
