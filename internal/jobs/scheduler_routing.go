package jobs

import (
	"errors"
	"fmt"
)

// enqueueUnits routes work units to the appropriate pool queues.
func (s *Scheduler) enqueueUnits(jobID string, units []WorkUnit) {
	if len(units) == 0 {
		return
	}

	s.mu.Lock()
	if _, ok := s.jobs[jobID]; !ok {
		s.mu.Unlock()
		s.logger.Warn("dropping work units for inactive job", "job_id", jobID, "count", len(units))
		return
	}
	s.pending[jobID] += len(units)
	bookSeq := s.jobSeq[jobID]
	s.mu.Unlock()

	for i := range units {
		unit := &units[i]
		unit.JobID = jobID
		if unit.BookSeq == 0 {
			unit.BookSeq = bookSeq
		}

		pool := s.findPool(unit)
		if pool == nil {
			s.logger.Error("no pool found for work unit",
				"unit_id", unit.ID,
				"type", unit.Type,
				"provider", unit.Provider,
			)
			s.emitFailure(unit, fmt.Errorf("no pool available for type %s provider %s", unit.Type, unit.Provider))
			continue
		}

		if err := pool.Submit(unit); err != nil {
			if errors.Is(err, ErrWorkerQueueFull) {
				// Backpressure: park for retry instead of failing. The unit stays
				// counted in s.pending, so completion accounting is unchanged.
				select {
				case s.requeue <- unit:
					continue
				default:
					// Requeue buffer itself is full: fall back to a failure result.
				}
			}
			s.logger.Warn("failed to submit to pool", "pool", pool.Name(), "error", err)
			s.emitFailure(unit, err)
		}
	}

	s.logger.Debug("enqueued work units", "job_id", jobID, "count", len(units))
}

// findPool finds an appropriate pool for the work unit.
func (s *Scheduler) findPool(unit *WorkUnit) WorkerPool {
	s.mu.RLock()
	defer s.mu.RUnlock()

	// CPU work units go to the CPU pool
	if unit.Type == WorkUnitTypeCPU {
		return s.cpuPool // May be nil if not initialized
	}

	// If specific provider requested, use that pool
	if unit.Provider != "" {
		if p, ok := s.pools[unit.Provider]; ok {
			// Verify type matches
			targetType := PoolTypeLLM
			if unit.Type == WorkUnitTypeOCR {
				targetType = PoolTypeOCR
			} else if unit.Type == WorkUnitTypeTTS {
				targetType = PoolTypeTTS
			}
			if p.Type() == targetType {
				return p
			}
		}
		return nil
	}

	// Otherwise find any pool of the right type
	targetType := PoolTypeLLM
	if unit.Type == WorkUnitTypeOCR {
		targetType = PoolTypeOCR
	} else if unit.Type == WorkUnitTypeTTS {
		targetType = PoolTypeTTS
	}

	for _, p := range s.pools {
		if p.Type() == targetType {
			return p
		}
	}

	return nil
}
