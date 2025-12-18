package jobs

import "fmt"

// enqueueUnits routes work units to the appropriate worker queues.
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

		worker := s.findWorker(unit)
		if worker == nil {
			s.logger.Error("no worker found for work unit",
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
					Error:      fmt.Errorf("no worker available for type %s provider %s", unit.Type, unit.Provider),
				},
			}
			continue
		}

		if err := worker.Submit(unit); err != nil {
			s.logger.Warn("failed to submit to worker", "worker", worker.Name(), "error", err)
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

// findWorker finds an appropriate worker for the work unit.
func (s *Scheduler) findWorker(unit *WorkUnit) WorkerInterface {
	s.mu.Lock()
	defer s.mu.Unlock()

	// CPU work units use round-robin across CPU workers
	if unit.Type == WorkUnitTypeCPU {
		if len(s.cpuWorkers) == 0 {
			return nil
		}
		// Round-robin selection
		w := s.cpuWorkers[s.cpuIndex]
		s.cpuIndex = (s.cpuIndex + 1) % len(s.cpuWorkers)
		return w
	}

	// If specific provider requested, use that
	if unit.Provider != "" {
		if w, ok := s.workers[unit.Provider]; ok {
			// Verify type matches
			if (unit.Type == WorkUnitTypeLLM && w.Type() == WorkerTypeLLM) ||
				(unit.Type == WorkUnitTypeOCR && w.Type() == WorkerTypeOCR) {
				return w
			}
		}
		return nil
	}

	// Otherwise find any worker of the right type
	targetType := WorkerTypeLLM
	if unit.Type == WorkUnitTypeOCR {
		targetType = WorkerTypeOCR
	}

	for _, w := range s.workers {
		if w.Type() == targetType {
			return w
		}
	}

	return nil
}
