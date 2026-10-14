#!/usr/bin/env python3
# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Example 04: Stateful Agent (Functional Style with Module State)
===============================================================

This example demonstrates state management using module-level variables.

Key Concepts:
- Module-level state (persists across requests)
- Request history tracking
- Caching mechanism
- Metrics collection
- Using global keyword

Usage:
    export ORG_JWT_TOKEN=<your-org-jwt>
    export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
    export SFDC_USER_ID=<user-id>
    export SFDC_APP_CONTEXT=<app-context>

    # Mock mode (author supplies the JWT)
    AGENTFORCE_BYOC_MOCK=1 python examples/04_stateful_agent.py

    # Agentforce runtime (default; JWT injected by the runtime)
    python examples/04_stateful_agent.py
"""

from datetime import datetime

from agentforce_byoc import get_client, get_logger

# Initialize logger
logger = get_logger(__name__)

# ============================================================================
# Module-Level State (persists across dc_function calls)
# ============================================================================
_request_count = 0
_request_history = []
_cache = {}
_startup_time = datetime.now()


def function(request: dict) -> dict:
    """
    Process request with state tracking and caching.

    This function demonstrates how to maintain state across requests
    using module-level variables in functional style.

    Args:
        request: Must contain a 'query' field

    Returns:
        Dictionary with response and metadata
    """
    global _request_count, _request_history, _cache

    # Increment request counter
    _request_count += 1
    request_start = datetime.now()

    query = request.get("query", "")

    if not query:
        logger.warning("Missing query")
        return {"status": "error", "error": "Missing 'query' in request"}

    logger.info(f"Processing request #{_request_count}", extra={"query": query[:50]})

    # Check cache first
    if query in _cache:
        logger.info("Cache hit!")
        response_text = _cache[query]
        cache_hit = True
    else:
        # Relay the LLM generations call. The tenant id, user id, and app
        # context are resolved from the environment (SFDC_CORE_TENANT_ID /
        # SFDC_USER_ID / SFDC_APP_CONTEXT).
        try:
            client = get_client()
            response_text = client.call_llm_generations(
                parameter={
                    "model": "llmgateway__OpenAIGPT35Turbo",
                    "prompt": query,
                    "max_tokens": 100,
                },
            )

            # Update cache
            _cache[query] = response_text
            logger.debug("Response cached")
            cache_hit = False

        except Exception as e:
            logger.error(f"Relay call failed: {e}")
            return {"status": "error", "error": str(e)}

    # Track request history
    request_duration = (datetime.now() - request_start).total_seconds()
    history_entry = {
        "request_number": _request_count,
        "query": query,
        "timestamp": request_start.isoformat(),
        "duration_seconds": request_duration,
        "cache_hit": cache_hit,
    }

    _request_history.append(history_entry)

    # Limit history size
    max_history = 10
    if len(_request_history) > max_history:
        _request_history = _request_history[-max_history:]

    # Calculate uptime
    uptime_seconds = (datetime.now() - _startup_time).total_seconds()

    return {
        "status": "success",
        "query": query,
        "response": response_text,
        "cache_hit": cache_hit,
        "metadata": {
            "request_number": _request_count,
            "duration_seconds": round(request_duration, 3),
            "uptime_seconds": round(uptime_seconds, 2),
            "cache_size": len(_cache),
            "history_size": len(_request_history),
        },
    }


def get_statistics() -> dict:
    """
    Get current agent statistics (helper function).

    Returns:
        Dictionary with performance metrics
    """
    uptime = (datetime.now() - _startup_time).total_seconds()

    return {
        "uptime_seconds": round(uptime, 2),
        "total_requests": _request_count,
        "cache_size": len(_cache),
        "history_size": len(_request_history),
        "startup_time": _startup_time.isoformat(),
    }


def main():
    """Run the agent with example queries."""
    print("=" * 60)
    print("Example 04: Stateful Agent (Functional)")
    print("=" * 60)

    # The tenant id, user id, and app context come from the environment
    # (SFDC_CORE_TENANT_ID / SFDC_USER_ID / SFDC_APP_CONTEXT).

    # Test queries (some repeated to demonstrate caching)
    test_queries = [
        "What is machine learning?",
        "Explain cloud computing.",
        "What is machine learning?",  # Cache hit
        "Define artificial intelligence.",
        "Explain cloud computing.",  # Cache hit
    ]

    print("\nProcessing requests...")
    print()

    for i, query in enumerate(test_queries, 1):
        print(f"{'─' * 60}")
        print(f"Request #{i}: {query}")
        print()

        response = function({"query": query})

        if response["status"] == "success":
            print(f"✅ Response: {str(response['response'])[:80]}...")
            print(f"   Cache Hit: {response['cache_hit']}")
            print(f"   Duration: {response['metadata']['duration_seconds']}s")
            print(f"   Cache Size: {response['metadata']['cache_size']}")
        else:
            print(f"❌ Error: {response['error']}")

        print()

    # Show statistics
    print("=" * 60)
    print("Agent Statistics")
    print("=" * 60)

    stats = get_statistics()
    print("\n📊 Performance Metrics:")
    print(f"   Total Requests: {stats['total_requests']}")
    print(f"   Uptime: {stats['uptime_seconds']}s")
    print(f"   Cache Size: {stats['cache_size']} entries")
    print(f"   History Size: {stats['history_size']} entries")
    print(f"   Startup Time: {stats['startup_time']}")

    print(f"\n{'=' * 60}")
    print("✅ Example completed successfully")
    print("=" * 60)
    print("\nKey Takeaways:")
    print("• Module-level variables persist across function calls")
    print("• Use 'global' keyword to modify module-level state")
    print("• State is shared across all requests in same process")
    print("• Helper functions can access module-level state")


if __name__ == "__main__":
    main()
