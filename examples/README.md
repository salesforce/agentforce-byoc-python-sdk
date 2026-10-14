# Agentforce BYOC SDK Examples

This directory contains example agents demonstrating SDK features using functional style.

## Running Examples

### 01_basic_agent.py (no relay)

Runs fully offline — no JWT or network required:

```bash
python examples/01_basic_agent.py
```

### Relay examples (02, 03, 04)

These relay LLM calls through the Agentforce Relay API, so they need a valid
org JWT (`ORG_JWT_TOKEN`) and a reachable endpoint for the tenant. The tenant
id, user id, and app context are read from the environment
(`SFDC_CORE_TENANT_ID` / `SFDC_USER_ID` / `SFDC_APP_CONTEXT`), which the runtime
injects in the sandbox and you export for local runs.

```bash
export ORG_JWT_TOKEN=<your-org-jwt>
export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
export SFDC_USER_ID=<user-id>
export SFDC_APP_CONTEXT=<app-context>
python examples/02_llm_agent.py
python examples/03_sentiment_analysis.py
python examples/04_stateful_agent.py
```

## Examples Overview

### 01_basic_agent.py

**Minimal agent** - Shows the simplest possible implementation.

- Basic function structure
- Simple request/response handling
- No LLM calls or external dependencies
- Good starting point for beginners

**What it demonstrates:**
```python
def function(request: dict) -> dict:
    message = request.get("message", "No message provided")
    return {
        "status": "success",
        "echo": message,
        "processed": True
    }
```

### 02_llm_agent.py

**Relay integration** - Demonstrates relaying an LLM call.

- Using `get_client()` to access the client
- Relaying with `call_llm_generations(parameter)`
- Handling the relay response envelope
- Error handling for relay calls

**What it demonstrates:**
```python
def function(request: dict) -> dict:
    client = get_client()
    # Tenant id, user id, and app context are read from the environment
    # (SFDC_CORE_TENANT_ID / SFDC_USER_ID / SFDC_APP_CONTEXT).
    response = client.call_llm_generations(
        parameter={
            "model": "llmgateway__OpenAIGPT35Turbo",
            "prompt": request["prompt"],
            "max_tokens": 150,
        },
    )
    return {"status": "success", "response": response}
```

### 03_sentiment_analysis.py

**Real-world use case** - Sentiment analysis agent.

- Practical example of LLM usage
- Request validation
- Structured response formatting
- Helper functions for code organization
- Production-ready patterns

**What it demonstrates:**
```python
def _build_prompt(text: str) -> str:
    """Build structured prompt for sentiment analysis."""
    return f"""Analyze the sentiment of this text...

Text: {text}

Sentiment:"""

def function(request: dict) -> dict:
    text = request.get("text", "")
    prompt = _build_prompt(text)
    # ... call LLM and parse response
```

### 04_stateful_agent.py

**State management** - Using module-level variables for state.

- Module-level state persists across requests
- Request history tracking
- Caching mechanism
- Metrics collection
- Using `global` keyword properly

**What it demonstrates:**
```python
# Module-level state
_request_count = 0
_cache = {}

def function(request: dict) -> dict:
    global _request_count
    _request_count += 1

    # Use cached results
    if query in _cache:
        return _cache[query]

    # ... process and cache
```

## Creating Your Own Agent

Start with this functional template:

```python
from agentforce_byoc import get_client, get_logger

logger = get_logger(__name__)

def function(request: dict) -> dict:
    """
    Entry point called by the Agentforce BYOC runtime.

    Args:
        request: Input data from Agentforce

    Returns:
        Dictionary response to send back to Agentforce
    """
    logger.info("Processing request")

    # Get input
    text = request.get("text", "")
    if not text:
        return {"error": "text field is required"}

    # Relay an LLM generations call. The tenant id, user id, and app context
    # are read from the environment (SFDC_CORE_TENANT_ID / SFDC_USER_ID /
    # SFDC_APP_CONTEXT).
    client = get_client()
    response = client.call_llm_generations(
        parameter={"prompt": text},
    )

    return {"response": response}

# Local testing
if __name__ == "__main__":
    result = function({"text": "test"})
    print(result)
```

## Testing Your Agent

### Standalone Testing

Each example can be run directly:

```bash
# Test basic agent (no relay, runs offline)
python examples/01_basic_agent.py

# Test a relay agent (needs an org JWT, tenant id, user id, and app context)
export ORG_JWT_TOKEN=<your-org-jwt>
export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
export SFDC_USER_ID=<user-id>
export SFDC_APP_CONTEXT=<app-context>
python examples/02_llm_agent.py
```

### Using the CLI

```bash
export ORG_JWT_TOKEN=<your-org-jwt>
export SFDC_CORE_TENANT_ID=core/<instance>-<fd>/<org-id>
export SFDC_USER_ID=<user-id>
export SFDC_APP_CONTEXT=<app-context>
agentforce run examples/02_llm_agent.py
```

## Common Patterns

### Request Validation

```python
def function(request: dict) -> dict:
    # Validate required fields
    required_fields = ["text", "user_id"]
    missing = [f for f in required_fields if f not in request]

    if missing:
        return {
            "status": "error",
            "error": f"Missing required fields: {', '.join(missing)}"
        }

    # Process valid request
    return process(request)
```

### Response Formatting

```python
def function(request: dict) -> dict:
    try:
        result = process(request)
        return {
            "status": "success",
            "data": result,
            "metadata": {
                "timestamp": datetime.utcnow().isoformat(),
                "model": "llmgateway__OpenAIGPT35Turbo"
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "metadata": {
                "timestamp": datetime.utcnow().isoformat()
            }
        }
```

### Caching

```python
_cache = {}
_cache_ttl = {}

def function(request: dict) -> dict:
    query = request.get("query", "")
    current_time = time.time()

    # Check cache
    if query in _cache and _cache_ttl.get(query, 0) > current_time:
        return {"response": _cache[query], "cached": True}

    # Process and cache
    result = process(query)
    _cache[query] = result
    _cache_ttl[query] = current_time + 3600  # 1 hour TTL

    return {"response": result, "cached": False}
```

## Best Practices

1. **Keep functions simple** - One function per responsibility
2. **Validate inputs early** - Check required fields upfront
3. **Handle errors gracefully** - Always return a response, even on error
4. **Log important events** - Use structured logging with context
5. **Test locally with `agentforce run`** - Iterate before packaging/deploying
6. **Use type hints** - Makes code more maintainable
7. **Document your functions** - Add docstrings explaining behavior

## Learn More

- [SDK Documentation](../README.md)
