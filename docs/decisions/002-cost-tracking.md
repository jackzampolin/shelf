# 2. Cost Tracking as First-Class Architectural Concern

**Date:** 2025-10-01

**Status:** Accepted

## Context

This is a hobby project funded out-of-pocket. Current investment: **a few hundred dollars** in API costs across ~10 full library runs (~$310 total). Each complete library run costs **~$31**.

**User economics matter:**
- Physical book: $20-30
- Digital processing: $5-15/book
- **That's 25-50% overhead** on the purchase price
- Scales badly: 100 books = $500-1500 in LLM costs

**Competitive positioning requires transparency:**
- ABBYY FineReader: $199 license + $0.40/book
- olmOCR: ~$0.20/book (GPU costs)
- Commercial services: $150-650/book
- **Shelf: $5-15/book** (break-even vs ABBYY at 50-100 books)

If there's a market for this, users need:
1. **Cost visibility** - Know what they're spending
2. **Cost control** - Choose models, control parallelism
3. **Cost optimization** - Local inference options to reduce costs

See Issue #87 for full competitive analysis.

## Decision

**Cost tracking is not a feature, it's an architectural driver.**

Track costs at every API call:
- MetricsManager records cost per page
- CLI displays cumulative costs per stage
- Model selection documented with cost implications
- CLAUDE.md requires approval before expensive operations

## Why This Shapes Architecture

Cost drives: **Granularity** (paragraphs balance quality/calls), **model selection** (gpt-4o-mini: 80% quality, 10% cost), **parallelism** (30 workers balance speed/cost), **infrastructure** (OpenRouter for unified tracking, MetricsManager for visibility), **features** (vision correction expensive but necessary, caching avoids redundant calls).

## The Real Costs

**Per book:** 100pg: $3-5, 200pg: $5-10, 400pg: $10-15
**At scale:** 50 books: $250-750, 100 books: $500-1500, 500 books: $2500-7500

These numbers directly inform decisions.

## Implementation

**Go implementation:**
- Every LLM/OCR call returns cost in result (ChatResult.CostUSD, OCRResult.CostUSD)
- Jobs track cumulative costs
- DefraDB stores cost history for audit
- CLAUDE.md requires approval for expensive operations

**Future:**
- Dashboard showing cost per book/stage
- Budget limits and alerts

## Consequences

**Enables:** Informed decisions (see costs before running), competitive positioning (transparent pricing, Issue #87), feature evaluation (cost/benefit analysis).

**Drives future:** Local inference integration, caching layer, model routing, batch optimization.

## Alternatives Considered

- **Ignore costs:** Surprise bills, can't make informed decisions. Rejected.
- **Post-hoc logs:** No real-time visibility, hard to attribute. Rejected.
- **Manual spreadsheets:** Error-prone, doesn't scale. Rejected.

## Market Reality & Future

**At scale, cost matters:** 100 books: Shelf ($500-1500) vs ABBYY ($240) vs Services ($15K-65K)

**Future:** Local inference (chandra, DeepSeek-OCR, moondream2) eliminates API costs. Break-even at ~50-100 books. Abstraction layer (`infra/llm/`) enables transition.

## Core Principle

**Economics shapes architecture.** Users paying per book need: visibility, control, predictability.

Cost tracking isn't accounting, it's **product-market fit**.
