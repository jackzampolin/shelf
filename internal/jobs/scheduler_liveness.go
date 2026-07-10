package jobs

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"
)

// heartbeatLoop periodically persists proof that each in-memory job is alive,
// plus the timestamp of the last handled work result.
func (s *Scheduler) heartbeatLoop(ctx context.Context) {
	ticker := time.NewTicker(heartbeatInterval)
	defer ticker.Stop()

	s.flushHeartbeats(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			s.flushHeartbeats(ctx)
		}
	}
}

func (s *Scheduler) flushHeartbeats(ctx context.Context) {
	if s.manager == nil {
		return
	}

	s.mu.RLock()
	progress := make(map[string]time.Time, len(s.jobs))
	for jobID := range s.jobs {
		progress[jobID] = s.lastProgress[jobID]
	}
	s.mu.RUnlock()

	now := time.Now().UTC()
	for jobID, lastProgress := range progress {
		if err := s.manager.UpdateHeartbeat(ctx, jobID, now, lastProgress); err != nil {
			s.logger.Warn("failed to persist job heartbeat", "job_id", jobID, "error", err)
		}
	}
}

// providerWaitChanged persists provider outages as a distinct, recoverable job
// state. Multiple provider outages compose: running resumes only after all of
// the providers blocking that job have recovered.
func (s *Scheduler) providerWaitChanged(provider, jobID string, waiting bool) {
	if jobID == "" {
		return
	}

	s.mu.Lock()
	if _, active := s.jobs[jobID]; !active {
		s.mu.Unlock()
		return
	}
	providers := s.waitingProviders[jobID]
	if providers == nil {
		providers = make(map[string]struct{})
		s.waitingProviders[jobID] = providers
	}
	if waiting {
		providers[provider] = struct{}{}
	} else {
		delete(providers, provider)
	}
	names := make([]string, 0, len(providers))
	for name := range providers {
		names = append(names, name)
	}
	sort.Strings(names)
	stillWaiting := len(names) > 0
	s.mu.Unlock()

	if s.manager == nil {
		return
	}
	ctx := s.schedulerContext()
	if stillWaiting {
		reason := fmt.Sprintf("waiting for provider recovery: %s", strings.Join(names, ", "))
		if err := s.manager.UpdateRuntimeStatus(ctx, jobID, StatusWaitingProvider, reason); err != nil {
			s.logger.Warn("failed to persist waiting_provider state", "job_id", jobID, "provider", provider, "error", err)
		}
		return
	}
	if err := s.manager.UpdateRuntimeStatus(ctx, jobID, StatusRunning, ""); err != nil {
		s.logger.Warn("failed to restore running state after provider recovery", "job_id", jobID, "provider", provider, "error", err)
	}
}
