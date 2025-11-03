# 4. OpenRouter API (Pragmatic Choice for Now)

**Date:** 2025-10-01

**Status:** Accepted (with planned evolution)

## Context

Need to experiment with multiple LLM providers while building out the pipeline. Requirements:
- **Cost tracking:** Every API call tracked (see ADR 003)
- **High volume:** Reliable at 100+ concurrent requests
- **Model flexibility:** Try gpt-4o, claude-3.5, grok, etc. without code changes
- **Rapid iteration:** Change models via config, not code

Each provider (OpenAI, Anthropic, X.ai) has different API, auth, pricing structure.

## Decision

**Use OpenRouter as unified LLM gateway for development and initial deployment.**

Single API key, consistent interface, automatic cost tracking via `/api/v1/models` endpoint with 24h pricing cache.

## Current Reality (Nov 2025)

**Consolidated around a single model:** `x-ai/grok-4-fast`

Why:
- Pragmatic cost/quality balance
- API consistency (fewer rate limit issues)
- Simplifies debugging (one model's behavior to understand)

This contradicts the "flexibility" rationale, but it's how we actually work - experiment broadly, then consolidate on what works.

## Why OpenRouter

Unified cost tracking (`/api/v1/models` endpoint), model experimentation (switch via config), high-volume reliability (100+ concurrent requests), simple integration (OpenAI-compatible, single API key).

**Pragmatic choice:** Get pipeline working first, optimize delivery later.

## The Future: Local Models

**Endgame:** Local models (chandra, DeepSeek-OCR, moondream2, olmOCR) for 1/10th cost, full privacy, no rate limits.

**Break-even at 50-100 books:** Current API costs ($500-1500) vs. one-time GPU ($500-1000).

## Strategic Sequencing

**Phase 1 (now):** Perfect techniques using flexible cloud APIs (OpenRouter).
**Phase 2 (future):** Optimize costs via local models (HuggingFace, ollama) + hybrid strategies.

`infra/llm/` abstraction supports both.

## Design for Swappability

`infra/llm/` abstraction enables: OpenRouter (now), direct APIs, local HuggingFace, hybrid routing.

To add local support: implement `infra/llm/providers/local.py`, add routing. No pipeline changes.

## Trade-offs Accepted

- **Markup (~10-15%):** Worth it for iteration speed ($30 → $33/run)
- **Third-party dependency:** Mitigation via abstraction layer
- **Less control:** Local models in Phase 2 address this

## Consequences

**Enables now:** Rapid experimentation, cost tracking (ADR 003), high-volume processing.

**Enables future:** Local integration, hybrid strategies, 1/10th cost optimization.

**Requires:** Local provider implementation, quality benchmarking, routing logic, GPU docs.

## Alternatives Considered

- **Direct provider APIs:** No unified cost tracking, more switching code. Rejected.
- **LiteLLM:** Less mature, unreliable pricing. Rejected.
- **Custom wrapper:** Reinventing OpenRouter, maintenance burden. Rejected.
- **Local models day one:** Slower iteration, premature optimization. Rejected.

## Core Principle

**Strategic sequencing: Perfect the approach first, optimize delivery later.**

OpenRouter enables fast iteration NOW. Local models enable cost optimization LATER. The abstraction layer (`infra/llm/`) makes the transition seamless when ready.

Current focus: Build reliable structure extraction techniques.
Future focus: Drive costs down 10x with local inference.
