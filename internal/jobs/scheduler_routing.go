package jobs

import "fmt"

// enqueueUnits routes work units to the appropriate pool queues.
func (s *Scheduler) enqueueUnits(jobID string, units []WorkUnit) {
	if len(units) == 0 {
		return
	}

	s.mu.Lock()
	s.pending[jobID] += len(units)
	s.mu.Unlock()

	for i := range units {
		unit := &units[i]
		unit.JobID = jobID

		pool := s.findPool(unit)
		if pool == nil {
			s.logger.Error("no pool found for work unit",
				"unit_id", unit.ID,
				"type", unit.Type,
				"provider", unit.Provider,
			)
			// Send failure result
			s.results <- workerResult{
				JobID: jobID,
				Unit:  unit,
				Result: WorkResult{
					WorkUnitID: unit.ID,
					Success:    false,
					Error:      fmt.Errorf("no pool available for type %s provider %s", unit.Type, unit.Provider),
				},
			}
			continue
		}

		if err := pool.Submit(unit); err != nil {
			s.logger.Warn("failed to submit to pool", "pool", pool.Name(), "error", err)
			// Send failure result
			s.results <- workerResult{
				JobID: jobID,
				Unit:  unit,
				Result: WorkResult{
					WorkUnitID: unit.ID,
					Success:    false,
					Error:      err,
				},
			}
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
