# Cost Tracking System

**Purpose**: Map the holistic cost tracking system and how cost data flows through the pipeline.

---

## Overview

Cost tracking is a **distributed system** with clear separation:
- **Producers:** Generate cost data (LLM calls)
- **Consumers:** Accumulate, persist, and report costs

**Core principle:** Costs accumulate across runs, never reset.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Cost Data Flow                           │
└─────────────────────────────────────────────────────────────┘

1. PRICING SOURCE
   └── pricing.py (PricingCache + CostCalculator)
       └── Fetches model pricing from OpenRouter (24hr cache)
       └── Converts token usage → USD cost

2. COST PRODUCER
   └── llm_client.py (LLMClient)
       └── Returns: (response, usage, cost)
       └── Detailed pattern: 03_llm_client.md

3. COST CONSUMERS

   a) Stage Accumulation
      └── Stages receive cost, add to self.stats['total_cost_usd']
      └── Examples: pipeline/correct.py, pipeline/fix.py

   b) Checkpoint Persistence
      └── checkpoint.py saves/loads accumulated costs
      └── Detailed pattern: 02_checkpointing.md

   c) Monitoring & Display
      └── tools/monitor.py, ar.py read checkpoint metadata
```

---

## Key Responsibilities

### Pricing Source (`pricing.py`)
- Fetches current OpenRouter model pricing (cached 24hrs)
- Calculates USD cost from token counts
- **File:** `pricing.py`

### Cost Producer (`llm_client.py`)
- Makes LLM API calls
- Returns cost per call (does NOT accumulate)
- **Pattern:** See [03_llm_client.md § Return Cost](03_llm_client.md)

### Cost Consumers

**Stages** - Accumulate costs in `self.stats['total_cost_usd']`
- Load existing costs from checkpoint on resume
- Add costs after successful LLM calls
- Save to checkpoint metadata

**Checkpoints** - Persist costs across runs
- Load: `checkpoint_state['metadata']['total_cost_usd']`
- Save: Include `total_cost_usd` in metadata
- **Pattern:** See [02_checkpointing.md § Load Existing Costs](02_checkpointing.md)

**Monitoring** - Display costs to users
- Real-time: Read from checkpoint metadata during execution
- Historical: Read from `structured/metadata.json`

---

## Design Principles

**Separation of Concerns**
- Pricing knows rates, LLMClient calculates, stages accumulate, checkpoints persist

**Single Source of Truth**
- Current: `self.stats['total_cost_usd']` (in-memory)
- Historical: checkpoint metadata (on-disk)

**Accumulation, Not Reset**
- Always load existing costs before starting
- Books often take multiple runs (resume capability)

---

## Anti-Patterns

❌ **Don't accumulate in LLMClient** - Stages own cost tracking
❌ **Don't reset costs on resume** - Must load existing from checkpoint
❌ **Don't hardcode pricing** - Use CostCalculator for dynamic pricing

---

## Integration Points

- **Checkpointing:** [02_checkpointing.md](02_checkpointing.md) - Cost persistence patterns
- **LLM Client:** [03_llm_client.md](03_llm_client.md) - Cost calculation patterns
- **Monitoring:** `tools/monitor.py`, `ar.py` - Display patterns
