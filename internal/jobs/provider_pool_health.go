package jobs

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"
)

// Health values reported in PoolStatus.Health.
const healthHealthy = "healthy"

// Circuit defaults. Constants by design (no config plumbing until tuning
// proves necessary); tests override via the circuit's cfg field.
const (
	defaultCircuitTripThreshold = 5
	defaultCircuitProbeInterval = 15 * time.Second
	// Zero means wait indefinitely. Provider outages are operational pauses, not
	// page-quality failures; queued/parked work replays when health recovers.
	defaultParkMaxAge = 0
)

// errParkFull is returned by park when the parked list is at capacity; the
// unit then fails through to its job as it would without a circuit.
var errParkFull = errors.New("circuit park capacity exceeded")

// circuitConfig tunes the provider health circuit breaker.
type circuitConfig struct {
	TripThreshold int           // consecutive infra failures that open the circuit
	ProbeInterval time.Duration // HealthCheck cadence while open
	ParkMaxAge    time.Duration // parked units older than this fail through
	ParkCapacity  int           // max parked units; overflow fails through
}

type parkedUnit struct {
	unit     *WorkUnit
	err      error // the final error the unit would have failed with
	parkedAt time.Time
}

// circuit is the per-pool health circuit breaker. While open, the dispatcher
// pauses and units that exhaust retries on infra errors park for replay
// instead of failing through to their jobs (ADR 006 degrade-and-continue is
// preserved by ParkMaxAge/ParkCapacity fail-through).
type circuit struct {
	cfg circuitConfig

	mu          sync.Mutex
	open        bool
	openedAt    time.Time
	consecFails int
	parked      []parkedUnit
	closedCh    chan struct{} // non-nil while open; closed when the circuit closes
}

// openWait returns a channel to wait on while the circuit is open, or nil if
// the circuit is closed. The channel is closed when the circuit closes.
func (c *circuit) openWait() <-chan struct{} {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.open {
		return nil
	}
	return c.closedCh
}

// recordFailure counts one infra-class provider failure. It reports whether
// this failure just tripped the circuit open (the caller starts the prober).
func (c *circuit) recordFailure() (justTripped bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.consecFails++
	if !c.open && c.consecFails >= c.cfg.TripThreshold {
		c.openLocked()
		return true
	}
	return false
}

// noteFinalFailure records the final infra-class failure of a work unit and,
// if the circuit is open (including having just been tripped by this very
// failure — the check is atomic), parks the unit for replay. It reports
// (parked, justTripped). Non-infra errors are ignored entirely.
func (c *circuit) noteFinalFailure(unit *WorkUnit, err error) (parked, justTripped bool) {
	if err == nil || !IsRetriableError(err) {
		return false, false
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.consecFails++
	if !c.open && c.consecFails >= c.cfg.TripThreshold {
		c.openLocked()
		justTripped = true
	}
	if !c.open {
		return false, justTripped
	}
	if len(c.parked) >= c.cfg.ParkCapacity {
		return false, justTripped
	}
	c.parked = append(c.parked, parkedUnit{unit: unit, err: err, parkedAt: time.Now()})
	return true, justTripped
}

// park attempts to park a unit on the open circuit (used directly by tests
// and the overflow invariant). Errors with errParkFull at capacity.
func (c *circuit) park(unit *WorkUnit, err error) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.parked) >= c.cfg.ParkCapacity {
		return errParkFull
	}
	c.parked = append(c.parked, parkedUnit{unit: unit, err: err, parkedAt: time.Now()})
	return nil
}

// recordSuccess resets the failure counter. A success while open is direct
// evidence the backend recovered: the circuit closes and the parked units are
// returned for replay.
func (c *circuit) recordSuccess() []parkedUnit {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.consecFails = 0
	if !c.open {
		return nil
	}
	return c.closeLocked()
}

// closeNow closes an open circuit (prober recovery path) and returns the
// parked units for replay.
func (c *circuit) closeNow() []parkedUnit {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.open {
		return nil
	}
	c.consecFails = 0
	return c.closeLocked()
}

// expireParked removes and returns parked units older than ParkMaxAge.
func (c *circuit) expireParked() []parkedUnit {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.parked) == 0 || c.cfg.ParkMaxAge <= 0 {
		return nil
	}
	cutoff := time.Now().Add(-c.cfg.ParkMaxAge)
	var expired []parkedUnit
	kept := c.parked[:0]
	for _, pu := range c.parked {
		if pu.parkedAt.Before(cutoff) {
			expired = append(expired, pu)
		} else {
			kept = append(kept, pu)
		}
	}
	c.parked = kept
	return expired
}

func (c *circuit) removeJob(jobID string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	kept := c.parked[:0]
	removed := 0
	for _, pu := range c.parked {
		if pu.unit.JobID == jobID {
			removed++
			continue
		}
		kept = append(kept, pu)
	}
	c.parked = kept
	return removed
}

// isOpen reports the circuit state.
func (c *circuit) isOpen() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.open
}

// status returns the health string and parked count for PoolStatus.
func (c *circuit) status() (health string, parkedCount int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.open {
		return fmt.Sprintf("circuit-open since %s", c.openedAt.UTC().Format(time.RFC3339)), len(c.parked)
	}
	return healthHealthy, len(c.parked)
}

// openLocked transitions closed->open. Caller holds c.mu.
func (c *circuit) openLocked() {
	c.open = true
	c.openedAt = time.Now()
	c.closedCh = make(chan struct{})
}

// closeLocked transitions open->closed, waking dispatcher waiters, and
// returns the parked units. Caller holds c.mu.
func (c *circuit) closeLocked() []parkedUnit {
	c.open = false
	close(c.closedCh)
	c.closedCh = nil
	parked := c.parked
	c.parked = nil
	return parked
}

// --- pool integration ---

// healthCheck probes the pool's provider.
func (p *ProviderWorkerPool) healthCheck(ctx context.Context) error {
	switch p.poolType {
	case PoolTypeLLM:
		return p.llmClient.HealthCheck(ctx)
	case PoolTypeOCR:
		return p.ocrProvider.HealthCheck(ctx)
	case PoolTypeTTS:
		return p.ttsProvider.HealthCheck(ctx)
	}
	return nil
}

// noteInfraFailure counts a mid-retry infra failure and starts the prober on
// a fresh trip.
func (p *ProviderWorkerPool) noteInfraFailure(ctx context.Context, jobID string) {
	if p.circuit.recordFailure() {
		p.onCircuitOpen(ctx, jobID)
	}
}

// noteCallSuccess resets the failure counter and, if a straggling in-flight
// success arrives while the circuit is open, closes it and replays.
func (p *ProviderWorkerPool) noteCallSuccess() {
	if parked := p.circuit.recordSuccess(); parked != nil {
		p.logger.Warn("provider circuit closed (in-flight success)", "replaying", len(parked))
		p.clearWaitingJobs()
		p.replayParked(parked)
	}
}

// onCircuitOpen logs the trip and starts the recovery prober.
func (p *ProviderWorkerPool) onCircuitOpen(ctx context.Context, triggerJobID string) {
	p.logger.Warn("provider circuit OPEN: pausing dispatch, probing for recovery",
		"trip_threshold", p.circuit.cfg.TripThreshold,
		"probe_interval", p.circuit.cfg.ProbeInterval)
	p.markJobWaiting(triggerJobID)
	for _, jobID := range p.queue.JobIDs() {
		p.markJobWaiting(jobID)
	}
	go p.probeUntilRecovered(ctx)
}

// probeUntilRecovered runs while the circuit is open: it expires overdue
// parked units (failing them through) and probes the provider's HealthCheck,
// closing the circuit and replaying parked units on the first success.
func (p *ProviderWorkerPool) probeUntilRecovered(ctx context.Context) {
	ticker := time.NewTicker(p.circuit.cfg.ProbeInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		if !p.circuit.isOpen() {
			return
		}
		for _, pu := range p.circuit.expireParked() {
			p.failParkedThrough(pu)
		}
		if err := p.healthCheck(ctx); err != nil {
			p.logger.Debug("provider health probe failed", "error", err)
			continue
		}
		parked := p.circuit.closeNow()
		p.logger.Warn("provider circuit CLOSED: backend recovered, resuming dispatch",
			"replaying", len(parked))
		p.clearWaitingJobs()
		p.replayParked(parked)
		return
	}
}

func (p *ProviderWorkerPool) markJobWaiting(jobID string) {
	if jobID == "" {
		return
	}
	p.waitMu.Lock()
	if _, exists := p.waitingJobs[jobID]; exists {
		p.waitMu.Unlock()
		return
	}
	p.waitingJobs[jobID] = struct{}{}
	callback := p.onWaitChange
	p.waitMu.Unlock()
	if callback != nil {
		callback(p.name, jobID, true)
	}
}

func (p *ProviderWorkerPool) clearWaitingJobs() {
	p.waitMu.Lock()
	jobIDs := make([]string, 0, len(p.waitingJobs))
	for jobID := range p.waitingJobs {
		jobIDs = append(jobIDs, jobID)
	}
	p.waitingJobs = make(map[string]struct{})
	callback := p.onWaitChange
	p.waitMu.Unlock()
	if callback != nil {
		for _, jobID := range jobIDs {
			callback(p.name, jobID, false)
		}
	}
}

func (p *ProviderWorkerPool) removeWaitingJob(jobID string) {
	p.waitMu.Lock()
	_, existed := p.waitingJobs[jobID]
	delete(p.waitingJobs, jobID)
	callback := p.onWaitChange
	p.waitMu.Unlock()
	if existed && callback != nil {
		callback(p.name, jobID, false)
	}
}

// replayParked re-submits parked units to the pool's queue.
func (p *ProviderWorkerPool) replayParked(parked []parkedUnit) {
	for _, pu := range parked {
		if p.jobCancelled(pu.unit.JobID) {
			continue
		}
		if err := p.queue.Push(pu.unit); err != nil {
			p.logger.Warn("failed to replay parked unit, failing through",
				"unit_id", pu.unit.ID, "error", err)
			p.failParkedThrough(pu)
		}
	}
}

// failParkedThrough delivers a parked unit's original failure to the
// scheduler and records its final metric (degrade-and-continue).
func (p *ProviderWorkerPool) failParkedThrough(pu parkedUnit) {
	result := WorkResult{
		WorkUnitID: pu.unit.ID,
		Success:    false,
		Error: fmt.Errorf("parked %s awaiting provider recovery, expired: %w",
			time.Since(pu.parkedAt).Round(time.Second), pu.err),
	}
	p.recordMetrics(context.Background(), pu.unit, &result)
	p.logger.Warn("parked work unit failed through", "unit_id", pu.unit.ID, "error", result.Error)
	p.results <- workerResult{
		JobID:  pu.unit.JobID,
		Unit:   pu.unit,
		Result: result,
	}
}
