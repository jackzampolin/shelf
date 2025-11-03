# 3. Cost Tracking as First-Class Architectural Concern

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
- **Scanshelf: $5-15/book** (break-even vs ABBYY at 50-100 books)

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

**Cost considerations drive:**

**1. Granularity choices:**
- Why paragraphs? Balance quality vs. API calls
- Each call costs money - how many do we make?
- Larger chunks = fewer calls but lower quality

**2. Model selection:**
- gpt-4o-mini default: 80% quality at 10% cost
- Expensive models available but opt-in
- Documented in config with pricing tiers

**3. Parallelism tuning:**
- More workers = faster but higher API rate
- Cost tracking shows if speed is worth expense
- Default 30 workers balances speed/cost

**4. Infrastructure choices:**
- OpenRouter: Unified cost tracking across providers
- MetricsManager: Real-time cost visibility
- Report CSV: Per-page cost breakdown

**5. Feature decisions:**
- Vision-based correction: Expensive but necessary for quality
- Multi-pass processing: Each pass adds cost
- Caching strategies: Avoid redundant API calls

## The Real Costs (Current Data)

**Per book processing:**
- Small book (100 pages): ~$3-5
- Average book (200 pages): ~$5-10
- Large book (400 pages): ~$10-15

**Per stage breakdown:**
- OCR (vision selection): ~$0.01-0.02/page
- Paragraph correction: ~$0.02-0.04/page
- Page labeling: ~$0.01-0.02/page
- ToC extraction: ~$0.50-1.00/book

**At scale:**
- 50 books: $250-750
- 100 books: $500-1500
- 500 books: $2500-7500

These numbers **directly inform architectural decisions**.

## Implementation

**Record costs after every API call:**
```python
# In paragraph_correct/tools/worker.py
result = call_openrouter_api(...)
metrics_manager.add_api_call(
    model=model,
    cost_usd=result.cost,
    tokens=result.tokens
)
```

**Display costs in CLI:**
```bash
$ shelf.py book roosevelt-autobiography info

💰 Total Pipeline Cost: $8.4523

Stage breakdown:
  OCR:                $2.1234
  Paragraph-Correct:  $5.2145
  Label-Pages:        $0.9144
  Extract-ToC:        $0.2000
```

**Config documents cost tiers:**
```python
# infra/config.py
vision_model_primary = "openai/gpt-4o-mini"      # $0.15/1M in, $0.60/1M out
vision_model_expensive = "anthropic/claude-3.5"  # $3.00/1M in, $15/1M out
```

**CLAUDE.md enforces approval:**
```markdown
NEVER run these operations without explicit user approval:
- shelf.py book <scan-id> process (costs $5-15)
- shelf.py batch <stage> (costs $31+ for full library)
```

## Consequences

**Enables informed decisions:**
- User sees cost before running
- Can choose cheaper models for experimentation
- Reports show where money is spent
- Per-page metrics reveal expensive pages

**Shapes feature development:**
- "Should we add X?" → "How much will it cost?"
- Vision features justified by quality gain
- Multi-pass approaches evaluated by cost/benefit
- Caching strategies prioritized

**Enables competitive positioning:**
- Transparent pricing (report.csv shows exact costs)
- Cost comparison vs alternatives (Issue #87)
- User can predict costs for their collection
- Self-hosted LLM support to reduce costs further

**Drives future architecture:**
- Local inference integration (reduce API costs)
- Caching layer (avoid redundant calls)
- Model routing (cheap models first, expensive if needed)
- Batch processing (optimize API rate limits)

## Alternatives Considered

**Ignore costs until later:**
- Problem: Surprise bills after processing 100 books
- Problem: Can't make informed architectural decisions
- Problem: Users can't budget for collections
- Rejected: Cost explosion kills adoption

**Post-hoc analysis from API logs:**
- Problem: Can't see costs during development
- Problem: Hard to attribute to specific stages
- Problem: Users don't see costs until bill arrives
- Rejected: Need real-time visibility

**Manual spreadsheet tracking:**
- Problem: Error-prone, incomplete
- Problem: Doesn't scale to per-page tracking
- Problem: Not accessible to users
- Rejected: Need automated, accurate tracking

## The Market Reality

If you're digitizing your personal library:
- 50 books: Scanshelf ($250-750) vs ABBYY ($230) vs Services ($7500-32500)
- 100 books: Scanshelf ($500-1500) vs ABBYY ($240) vs Services ($15000-65000)
- 500 books: Scanshelf ($2500-7500) vs ABBYY ($400) vs Services ($75000-325000)

**At scale, cost matters.** Transparency enables users to:
- Budget for their collection
- Choose cost vs. quality tradeoffs
- Optimize processing strategies
- Consider self-hosted alternatives

## The Future: Local Inference

**Goal:** Support self-hosted LLMs to eliminate API costs.

Why this matters:
- One-time GPU cost vs. per-book API costs
- Break-even at ~50-100 books
- Full privacy (no cloud services)
- Unlimited processing (no rate limits)

Cost tracking architecture enables this transition:
- Abstraction layer already in place (infra/llm/)
- Metrics system works for local or cloud
- Users can compare local vs. cloud costs
- Hybrid strategies possible (local for cheap tasks, API for complex)

## Core Principle

**Economics shapes architecture.**

If users are paying per book, they need:
1. **Visibility** - What does it cost?
2. **Control** - How do I reduce costs?
3. **Predictability** - What will my collection cost?

Cost tracking isn't accounting, it's **product-market fit**.
