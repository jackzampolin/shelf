# 5. OpenRouter API (Over Direct Provider APIs)

**Date:** 2025-10-01

**Status:** Accepted

**Context:**
Need access to multiple LLM providers (OpenAI, Anthropic, X.ai) for model flexibility. Each provider has different API, auth, pricing.

**Decision:**
Use OpenRouter as unified gateway. Single API key, consistent interface, automatic cost tracking via `/api/v1/models` endpoint.

**Alternatives Considered:**
- Direct API calls to each provider (OpenAI SDK, Anthropic SDK, etc.)
- LiteLLM as abstraction layer
- Build custom multi-provider wrapper

**Consequences:**
- Model switching is config change (no code changes)
- Single source of pricing data (24h cache)
- Dependency on third-party service
- Slight pricing markup (~10-15%)
- Enables rapid iteration and model experimentation
