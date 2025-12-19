package jobs

import (
	"context"
	"fmt"
	"runtime"

	"github.com/jackzampolin/shelf/internal/providers"
)

// RegisterFactory registers a job factory for a job type.
// Required for resuming jobs after restart.
func (s *Scheduler) RegisterFactory(jobType string, factory JobFactory) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.factories[jobType] = factory
	s.logger.Debug("job factory registered", "type", jobType)
}

// RegisterWorker adds a worker to the scheduler.
// Must be called before Start.
func (s *Scheduler) RegisterWorker(w WorkerInterface) {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Initialize worker with shared results channel
	w.init(s.results)

	s.workers[w.Name()] = w
	s.logger.Info("worker registered", "name", w.Name(), "type", w.Type())
}

// InitFromRegistry creates workers from all providers in the registry.
// This is the recommended way to set up workers - one provider = one worker.
// Each worker pulls its rate limit from the provider's configured value.
// If runHealthChecks is true, each provider is health-checked before creating its worker.
func (s *Scheduler) InitFromRegistry(registry *providers.Registry) error {
	return s.InitFromRegistryWithHealthCheck(context.Background(), registry, false)
}

// InitFromRegistryWithHealthCheck creates workers with optional health checking.
// When runHealthChecks is true, verifies each provider is reachable before creating workers.
// Failed health checks are logged as warnings but don't prevent worker creation.
func (s *Scheduler) InitFromRegistryWithHealthCheck(ctx context.Context, registry *providers.Registry, runHealthChecks bool) error {
	// Create workers from LLM clients
	for name, client := range registry.LLMClients() {
		// Optional health check
		if runHealthChecks {
			if err := client.HealthCheck(ctx); err != nil {
				s.logger.Warn("LLM provider health check failed",
					"name", name,
					"error", err,
				)
				// Continue anyway - let the worker be created
			} else {
				s.logger.Info("LLM provider health check passed", "name", name)
			}
		}

		worker, err := NewWorker(WorkerConfig{
			Name:      name,
			LLMClient: client,
			Logger:    s.logger,
			Sink:      s.sink,
			// RPS pulled from client.RequestsPerSecond() by NewWorker
		})
		if err != nil {
			return fmt.Errorf("failed to create LLM worker %s: %w", name, err)
		}
		s.RegisterWorker(worker)
	}

	// Create workers from OCR providers
	for name, provider := range registry.OCRProviders() {
		// Optional health check
		if runHealthChecks {
			if err := provider.HealthCheck(ctx); err != nil {
				s.logger.Warn("OCR provider health check failed",
					"name", name,
					"error", err,
				)
				// Continue anyway - let the worker be created
			} else {
				s.logger.Info("OCR provider health check passed", "name", name)
			}
		}

		worker, err := NewWorker(WorkerConfig{
			Name:        name,
			OCRProvider: provider,
			Logger:      s.logger,
			Sink:        s.sink,
			// RPS pulled from provider.RequestsPerSecond() by NewWorker
		})
		if err != nil {
			return fmt.Errorf("failed to create OCR worker %s: %w", name, err)
		}
		s.RegisterWorker(worker)
	}

	s.logger.Info("initialized workers from registry",
		"llm_workers", len(registry.LLMClients()),
		"ocr_workers", len(registry.OCRProviders()),
	)

	return nil
}

// InitCPUWorkers creates n CPU workers for CPU-bound tasks.
// If n <= 0, uses runtime.NumCPU().
// Returns the created workers so callers can register task handlers.
func (s *Scheduler) InitCPUWorkers(n int) []*CPUWorker {
	if n <= 0 {
		n = runtime.NumCPU()
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	workers := make([]*CPUWorker, n)
	for i := 0; i < n; i++ {
		w := NewCPUWorker(CPUWorkerConfig{
			Name:   fmt.Sprintf("cpu-%d", i),
			Logger: s.logger,
		})
		w.init(s.results)
		workers[i] = w
		s.workers[w.Name()] = w
	}
	s.cpuWorkers = workers

	s.logger.Info("initialized CPU workers", "count", n)
	return workers
}

// RegisterCPUHandler registers a task handler on all CPU workers.
// Convenience method - equivalent to calling RegisterHandler on each worker.
func (s *Scheduler) RegisterCPUHandler(taskName string, handler CPUTaskHandler) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	for _, w := range s.cpuWorkers {
		w.RegisterHandler(taskName, handler)
	}
	s.logger.Debug("registered CPU handler on all workers", "task", taskName, "workers", len(s.cpuWorkers))
}

// GetWorker returns a worker by name.
func (s *Scheduler) GetWorker(name string) (WorkerInterface, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	w, ok := s.workers[name]
	return w, ok
}

// ListWorkers returns all worker names.
func (s *Scheduler) ListWorkers() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	names := make([]string, 0, len(s.workers))
	for name := range s.workers {
		names = append(names, name)
	}
	return names
}
