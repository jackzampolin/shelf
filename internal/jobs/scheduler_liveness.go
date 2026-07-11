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
	s.mu.Unlock()

	if s.manager == nil {
		return
	}
	ctx := s.schedulerContext()
	_, err := retryTransientOperation(ctx, s.logger, "persist provider runtime state", jobID, func() (struct{}, error) {
		// Recompute the desired state on every attempt. Provider callbacks and job
		// completion can race a transient Defra write; retries must converge to
		// the newest in-memory truth rather than resurrecting a stale state.
		s.mu.RLock()
		_, active := s.jobs[jobID]
		current := s.waitingProviders[jobID]
		names := make([]string, 0, len(current))
		for name := range current {
			names = append(names, name)
		}
		s.mu.RUnlock()
		if !active {
			return struct{}{}, nil
		}

		sort.Strings(names)
		status := StatusRunning
		reason := ""
		if len(names) > 0 {
			status = StatusWaitingProvider
			reason = fmt.Sprintf("waiting for provider recovery: %s", strings.Join(names, ", "))
		}
		return struct{}{}, s.manager.UpdateRuntimeStatus(ctx, jobID, status, reason)
	})
	if err != nil {
		s.logger.Warn("failed to persist provider runtime state", "job_id", jobID, "provider", provider, "error", err)
	}
}
