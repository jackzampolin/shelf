# Provider Health Circuit Breaker + Endpoint Failure Cooldowns — Design

**Date:** 2026-07-06
**Status:** Approved
**Motivation:** During run 4 (2026-07-06 06:46–06:52 PT) both chandra OCR nodes went dark for ~6 minutes. The pool kept dispatching, and 139 work units burned their 3 retries into a dead backend and were recorded as failed pages. Same class of incident in run 3 (98 failures). The engine degrades correctly, but the pages are lost to the run when they didn't need to be.

## Goals

1. When a provider backend is down (all endpoints), stop burning retries: pause dispatch, probe health, resume automatically.
2. Rescue units that exhaust retries during an outage window: park and replay on recovery instead of failing them through to jobs.
3. Single-node outages degrade to reduced capacity instead of a ~50% error rate: the chandra OCR client adopts the per-endpoint failure cooldowns the LLM client already uses.
4. Preserve degrade-and-continue: if the backend never recovers, parked units eventually fail through exactly as today.

## Non-goals

- No config plumbing for thresholds (constants first; hot-reloadable config only if tuning proves necessary).
- No scheduler changes — the existing requeue/backpressure machinery is untouched.
- No behavior change for content-class failures (bad page, empty OCR result): those never trip the circuit and are not rescued.

## Design

### Circuit breaker (per ProviderWorkerPool)

New `internal/jobs/provider_pool_health.go` owning a small state machine:

- **States:** `closed` (normal) and `open` (paused). No half-open state: the prober's successful `HealthCheck()` is the half-open probe.
- **Trip condition:** N consecutive infra-class failures (`circuitTripThreshold = 5`). Classification uses the existing `jobs.IsRetriableError` (`internal/jobs/error_class.go`): only errors it reports as retriable (transport/connection/EOF-class) count toward the trip; content-class errors reset nothing and trip nothing. Any success resets the counter.
- **While open:** the dispatcher does not hand units to workers (it blocks before `rateLimiter.Wait`, checking the circuit). A prober goroutine calls the provider's existing `HealthCheck(ctx)` every `circuitProbeInterval = 15s`. First success closes the circuit and wakes the dispatcher.
- **Park-and-replay:** a work unit that exhausts its retries while the circuit is open (or whose final failure trips it) is appended to a bounded parked list instead of being returned as a failure. On circuit close, parked units are re-submitted to the pool ahead of new work. Parking is capped by age: `parkMaxAge = 30m` — a unit parked longer fails through to its job with the original error (degrade-and-continue preserved). Parked list capacity is `4 * workerCount`; beyond that, units fail through immediately (protects memory during long outages with big fan-out).
- **Metrics/observability:** state transitions logged at WARN with timestamps and consecutive-failure count. Pool `Status()` gains `Health string` ("healthy" | "circuit-open since <RFC3339>") and `ParkedUnits int`; the status endpoint (`shelf api status`) surfaces both per provider.
- **Failure recording:** a parked-and-replayed unit records only its final outcome metric (success on replay, or failure at park expiry). The retries burned before parking already recorded failure metrics as today — no change; the harvest can still see the outage shape.

### Endpoint cooldowns for chandra (the C wiring)

`internal/providers/chandra_ocr.go` adopts the exact pattern from `openrouter_http.go:112-119`: on a per-request transport failure, `endpoints.MarkFailure(baseURL, endpointFailureCooldown)`; on success, `MarkSuccess(baseURL)`. `EndpointPool.Next()` already skips cooled-down endpoints, so a single dead node drops out of rotation and the pool runs at half capacity with zero errors. Constant reuse: the same `endpointFailureCooldown` value the LLM client uses.

### Interaction between the two layers

Endpoint cooldowns handle partial outages (some endpoints alive → requests keep succeeding → circuit stays closed). The circuit handles total outages (every endpoint failing → consecutive failures accumulate → trip). When all endpoints are cooled down, `Next()` falls back to round-robin over all of them (existing EndpointPool behavior), so requests still flow and fail — that is what feeds the circuit's counter. No coordination code needed between the layers.

## Testing

Unit tests in `internal/jobs/` using the existing mock providers (`providers/mock.go` failure injection):

1. Circuit trips after exactly N consecutive infra failures; a success at N-1 resets the counter.
2. Content-class errors (mock returns a non-infra error) never trip the circuit regardless of count.
3. While open: dispatcher stops (no provider calls observed); prober recovery closes it and dispatch resumes.
4. Park-and-replay: units exhausting retries while open are parked, replayed on close, and complete successfully; the job sees success, not failure.
5. Park expiry: with a short test `parkMaxAge`, parked units fail through to the job after the cap.
6. Parked-capacity overflow fails through immediately.
7. Chandra endpoint marking: after a failure on endpoint A, subsequent `Next()` calls avoid A until cooldown lapses (mirrors existing `openrouter_http` behavior; test via httptest servers, one failing).

## Deployment

Lands on `local-inference`; takes effect at the next server restart (after run 4 completes — never mid-run). No schema, config, or API changes required.
