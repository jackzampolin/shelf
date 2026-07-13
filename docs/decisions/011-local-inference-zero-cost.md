# ADR 011: Zero Marginal Cost for Local Inference

## Status
Accepted

## Context
ADR 002 (Cost Tracking) treats per-call dollar cost as a first-class signal,
sourced from provider responses. OpenRouter returns cost fields such as `cost`
and `native_total_cost`. With inference moving to self-hosted models on local
hardware (Qwen3.6-35B-A3B-NVFP4 and Chandra OCR on the DGX Sparks), there is no
per-call dollar cost. The marginal cost of a call is effectively zero, aside
from amortized hardware and electricity.

## Decision
Local provider implementations report `CostUSD: 0` on their `ChatResult` or
`OCRResult`. The existing metrics path already accommodates this:
`metrics.Metric.ToMap` only emits `cost_usd` when it is greater than zero, so
zero-cost local calls record no cost field while still recording tokens,
queue/execution latency, provider, and model.

For local inference the meaningful signals become throughput (tokens/sec),
latency, and future GPU utilization rather than dollars. Dashboards and
summaries should not treat a missing or zero `cost_usd` as an error for local
providers.

## Consequences
- No schema or code change is required to support zero-cost calls.
- Cost-based dashboards will show $0 for local providers; this is expected.
- If energy-cost estimation is desired later, it can be layered on as a
  separate, explicit estimate rather than overloading `cost_usd`.
- Cloud providers (OpenRouter, Mistral, OpenAI) remain registerable for A/B
  comparison and continue to report real dollar costs.
