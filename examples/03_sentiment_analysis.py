#!/usr/bin/env python3
# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Example 03: Sentiment Analysis Agent (Functional Style)
=======================================================

This example demonstrates a real-world use case with functional style.

Key Concepts:
- Production-ready functional agent
- Input validation
- Structured prompt engineering
- Response parsing
- Error handling

Usage:
    export ORG_JWT_TOKEN=<your-org-jwt>
    export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
    export SFDC_USER_ID=<user-id>
    export SFDC_APP_CONTEXT=<app-context>

    # Mock mode (author supplies the JWT)
    AGENTFORCE_BYOC_MOCK=1 python examples/03_sentiment_analysis.py

    # Agentforce runtime (default; JWT injected by the runtime)
    python examples/03_sentiment_analysis.py
"""

from agentforce_byoc import get_client, get_logger

# Initialize logger
logger = get_logger(__name__)


def _build_prompt(text: str, context: str = "") -> str:
    """
    Build a structured prompt for sentiment analysis.

    Args:
        text: Text to analyze
        context: Additional context

    Returns:
        Formatted prompt string
    """
    prompt = f"""Analyze the sentiment of the following text.

Text to analyze:
\"\"\"{text}\"\"\"
"""

    if context:
        prompt += f"""
Additional context:
{context}
"""

    prompt += """
Provide your analysis in this format:
- Sentiment: [positive/negative/neutral]
- Confidence: [high/medium/low]
- Reasoning: [brief explanation]

Analysis:"""

    return prompt


def _parse_sentiment_response(llm_response: str) -> dict:
    """
    Parse LLM response text into structured sentiment data.

    Args:
        llm_response: LLM response text (extracted from the relay envelope)

    Returns:
        Dictionary with sentiment, confidence, and reasoning
    """
    response_lower = llm_response.lower()

    # Determine sentiment
    if "positive" in response_lower:
        sentiment = "positive"
    elif "negative" in response_lower:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    # Determine confidence
    if "high" in response_lower:
        confidence = "high"
    elif "low" in response_lower:
        confidence = "low"
    else:
        confidence = "medium"

    # Extract reasoning
    reasoning = llm_response.strip()

    return {"sentiment": sentiment, "confidence": confidence, "reasoning": reasoning}


def function(request: dict) -> dict:
    """
    Analyze sentiment of the provided text.

    Args:
        request: Must contain:
            - 'text': Text to analyze (required)
            - 'context': Additional context (optional)

    Returns:
        Dictionary with sentiment analysis results
    """
    # Validate input
    text = request.get("text", "").strip()

    if not text:
        logger.warning("Empty text received for sentiment analysis")
        return {"status": "error", "error": "Missing or empty 'text' field in request"}

    context = request.get("context", "")

    logger.info(
        "Analyzing sentiment", extra={"text_length": len(text), "has_context": bool(context)}
    )

    # Construct prompt
    prompt = _build_prompt(text, context)

    try:
        # Relay the LLM generations call. `parameter` is the raw LLM request
        # body, passed through to the Relay API as-is. The tenant id, user id,
        # and app context are resolved from the environment
        # (SFDC_CORE_TENANT_ID / SFDC_USER_ID / SFDC_APP_CONTEXT).
        client = get_client()
        relay_response = client.call_llm_generations(
            parameter={
                "model": "llmgateway__OpenAIGPT35Turbo",
                "prompt": prompt,
                "max_tokens": 200,
            },
        )

        # The relay envelope is {body, requestId, traceId}; the LLM text lives
        # in the upstream body. Fall back to the stringified envelope.
        llm_text = str(relay_response.get("body", relay_response))

        # Parse response
        sentiment_result = _parse_sentiment_response(llm_text)

        logger.info(
            "Sentiment analysis completed", extra={"sentiment": sentiment_result["sentiment"]}
        )

        return {
            "status": "success",
            "text": text,
            "sentiment": sentiment_result["sentiment"],
            "confidence": sentiment_result["confidence"],
            "reasoning": sentiment_result["reasoning"],
            "raw_llm_response": relay_response,
        }

    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        return {"status": "error", "error": str(e), "text": text}


def main():
    """Run the agent with example customer feedback."""
    print("=" * 60)
    print("Example 03: Sentiment Analysis (Functional)")
    print("=" * 60)

    # The tenant id, user id, and app context come from the environment
    # (SFDC_CORE_TENANT_ID / SFDC_USER_ID / SFDC_APP_CONTEXT).

    # Test cases with different sentiments
    test_cases = [
        {
            "text": "This product is amazing! Best purchase I've ever made. Highly recommended!",
            "context": "5-star product review",
        },
        {
            "text": "Terrible experience. The product broke after one day and customer service was unhelpful.",
            "context": "1-star product review",
        },
        {
            "text": "The product works as expected. Nothing special, but does the job.",
            "context": "3-star product review",
        },
        {"text": "I'm not sure how I feel about this. It has good features but also some issues."},
    ]

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'─' * 60}")
        print(f"Test Case {i}")
        print(f"{'─' * 60}")
        print(f"Text: {test_case['text'][:80]}...")
        if test_case.get("context"):
            print(f"Context: {test_case['context']}")
        print()

        response = function(test_case)

        print(f"Status: {response['status']}")
        if response["status"] == "success":
            print(f"Sentiment: {response['sentiment'].upper()}")
            print(f"Confidence: {response['confidence']}")
            print(f"\nReasoning:\n{response['reasoning']}")
        else:
            print(f"Error: {response['error']}")

    print(f"\n{'=' * 60}")
    print("✅ Example completed successfully")
    print("=" * 60)
    print("\nNote: Both runtimes relay over the network and need a valid")
    print("ORG_JWT_TOKEN and a reachable endpoint for the tenant.")


if __name__ == "__main__":
    main()
