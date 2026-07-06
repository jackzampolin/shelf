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
- **Failure recording:** metrics are recorded once per work unit (after retries), not per attempt. A parked unit records only its final outcome metric — success on replay, or failure at park expiry. The outage shape remains visible via the pre-trip fail-through units, the WARN transition logs, and the circuit-open status field.
- **Queued work during a prolonged outage:** while the circuit is open, queued units simply wait (dispatch is paused). A backend that never recovers therefore pauses that provider's pipeline instead of failing thousands of pages — operator-visible via the `Health` field in `/api/status` — and only parked units fail through (at ParkMaxAge). This is a deliberate trade-off in favor of overnight batch runs surviving operator-fixable outages.
- **Replay ordering:** parked units re-enter through the pool's priority queue on circuit close; they compete with queued work at their original priority rather than jumping the line.

### Endpoint cooldowns for chandra (the C wiring)

**Verified already present during implementation** — no new code needed. Chandra delegates to the shared `OpenAICompatClient` (`chandra_ocr.go` constructor passes `BaseURLs`, and `openai_compat.go:59` builds the `EndpointPool`); the shared HTTP layer (`openrouter_http.go:112-119`) performs `MarkFailure`/`MarkSuccess` on every request. The behavior is pinned by the existing regression test `TestOpenAICompatClient_CoolsDownFailingEndpoint` (`openai_compat_test.go:137`). A single dead node drops out of rotation and the pool runs at half capacity with zero errors.

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
