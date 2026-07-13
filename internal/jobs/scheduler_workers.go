package jobs

import (
	"context"
	"fmt"
	"runtime"
	"time"

	"github.com/jackzampolin/shelf/internal/providers"
)

var providerHealthCheckTimeout = 5 * time.Second

// RegisterFactory registers a job factory for a job type.
// Required for resuming jobs after restart.
func (s *Scheduler) RegisterFactory(jobType string, factory JobFactory) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.factories[jobType] = factory
	s.logger.Debug("job factory registered", "type", jobType)
}

// RegisterPool adds a worker pool to the scheduler.
// If the scheduler is already running, the pool is started immediately.
func (s *Scheduler) RegisterPool(p WorkerPool) {
	s.mu.Lock()
	if providerPool, ok := p.(*ProviderWorkerPool); ok {
		providerPool.onWaitChange = s.providerWaitChanged
	}

	// Initialize pool with shared results channel
	p.init(s.results)

	s.pools[p.Name()] = p
	running := s.running
	ctx := s.ctx
	s.mu.Unlock()

	s.logger.Debug("pool registered", "name", p.Name(), "type", p.Type())

	// If scheduler already running, start pool immediately.
	if running {
		if ctx == nil {
			ctx = context.Background()
		}
		go p.Start(ctx)
		s.logger.Debug("pool started after scheduler already running", "name", p.Name(), "type", p.Type())
	}
}

// InitFromRegistry creates pools from all providers in the registry.
// This is the recommended way to set up pools - one provider = one pool.
// Each pool pulls its rate limit from the provider's configured value.
func (s *Scheduler) InitFromRegistry(registry *providers.Registry) error {
	return s.InitFromRegistryWithHealthCheck(context.Background(), registry, false, false)
}

// InitFromRegistryStrict runs health checks and fails fast on the first unreachable provider.
func (s *Scheduler) InitFromRegistryStrict(ctx context.Context, registry *providers.Registry) error {
	return s.InitFromRegistryWithHealthCheck(ctx, registry, true, true)
}

// InitFromRegistryWithHealthCheck creates pools with optional health checking.
// When runHealthChecks is true, verifies each provider is reachable before creating pools.
// Failed health checks are logged as warnings unless failFast is true.
func (s *Scheduler) InitFromRegistryWithHealthCheck(ctx context.Context, registry *providers.Registry, runHealthChecks, failFast bool) error {
	// Create pools from LLM clients
	for name, client := range registry.LLMClients() {
		var healthErr error
		if runHealthChecks {
			checkCtx, cancel := context.WithTimeout(ctx, providerHealthCheckTimeout)
			healthErr = client.HealthCheck(checkCtx)
			cancel()
			if healthErr != nil {
				if failFast {
					return fmt.Errorf("LLM provider %q failed health check: %w", name, healthErr)
				}
				s.logger.Warn("LLM provider health check failed", "name", name, "error", healthErr)
			} else {
				s.logger.Debug("LLM provider health check passed", "name", name)
			}
		}

		pool, err := NewProviderWorkerPool(ProviderWorkerPoolConfig{
			Name:      name,
			LLMClient: client,
			Logger:    s.logger,
			Sink:      s.sink,
		})
		if err != nil {
			return fmt.Errorf("failed to create LLM pool %s: %w", name, err)
		}
		s.RegisterPool(pool)
		pool.openOnStartup(ctx, healthErr)
	}

	// Create pools from OCR providers
	for name, provider := range registry.OCRProviders() {
		var healthErr error
		if runHealthChecks {
			checkCtx, cancel := context.WithTimeout(ctx, providerHealthCheckTimeout)
			healthErr = provider.HealthCheck(checkCtx)
			cancel()
			if healthErr != nil {
				if failFast {
					return fmt.Errorf("OCR provider %q failed health check: %w", name, healthErr)
				}
				s.logger.Warn("OCR provider health check failed", "name", name, "error", healthErr)
			} else {
				s.logger.Debug("OCR provider health check passed", "name", name)
			}
		}

		pool, err := NewProviderWorkerPool(ProviderWorkerPoolConfig{
			Name:        name,
			OCRProvider: provider,
			Logger:      s.logger,
			Sink:        s.sink,
		})
		if err != nil {
			return fmt.Errorf("failed to create OCR pool %s: %w", name, err)
		}
		s.RegisterPool(pool)
		pool.openOnStartup(ctx, healthErr)
	}

	// Create pools from TTS providers
	for name, provider := range registry.TTSProviders() {
		var healthErr error
		if runHealthChecks {
			checkCtx, cancel := context.WithTimeout(ctx, providerHealthCheckTimeout)
			healthErr = provider.HealthCheck(checkCtx)
			cancel()
			if healthErr != nil {
				if failFast {
					return fmt.Errorf("TTS provider %q failed health check: %w", name, healthErr)
				}
				s.logger.Warn("TTS provider health check failed", "name", name, "error", healthErr)
			} else {
				s.logger.Debug("TTS provider health check passed", "name", name)
			}
		}

		pool, err := NewProviderWorkerPool(ProviderWorkerPoolConfig{
			Name:        name,
			TTSProvider: provider,
			Logger:      s.logger,
			Sink:        s.sink,
		})
		if err != nil {
			return fmt.Errorf("failed to create TTS pool %s: %w", name, err)
		}
		s.RegisterPool(pool)
		pool.openOnStartup(ctx, healthErr)
	}

	s.logger.Info("initialized pools from registry",
		"llm_pools", len(registry.LLMClients()),
		"ocr_pools", len(registry.OCRProviders()),
		"tts_pools", len(registry.TTSProviders()),
	)

	return nil
}

// RefreshProviderClients applies same-name provider replacements from a
// hot-reloaded registry to existing scheduler pools. Queued, in-flight, and
// circuit-parked work stays attached to the original pool; the next attempt or
// health probe uses the new client. Pool sizing and rate limits intentionally
// remain restart-scoped because changing goroutine topology in place would make
// in-flight accounting ambiguous.
func (s *Scheduler) RefreshProviderClients(registry *providers.Registry) int {
	s.mu.RLock()
	pools := make(map[string]*ProviderWorkerPool, len(s.pools))
	for name, candidate := range s.pools {
		if pool, ok := candidate.(*ProviderWorkerPool); ok {
			pools[name] = pool
		}
	}
	s.mu.RUnlock()

	refreshed := 0
	for name, pool := range pools {
		var err error
		switch pool.Type() {
		case PoolTypeLLM:
			var client providers.LLMClient
			client, err = registry.GetLLM(name)
			if err == nil {
				err = pool.replaceProvider(client, nil, nil)
			}
		case PoolTypeOCR:
			var provider providers.OCRProvider
			provider, err = registry.GetOCR(name)
			if err == nil {
				err = pool.replaceProvider(nil, provider, nil)
			}
		case PoolTypeTTS:
			var provider providers.TTSProvider
			provider, err = registry.GetTTS(name)
			if err == nil {
				err = pool.replaceProvider(nil, nil, provider)
			}
		}
		if err != nil {
			s.logger.Warn("provider pool not refreshed from config",
				"name", name, "type", pool.Type(), "error", err)
			continue
		}
		refreshed++
		s.logger.Info("provider pool client refreshed from config",
			"name", name, "type", pool.Type())
	}
	return refreshed
}

// InitCPUPool creates a single CPU worker pool.
// If workerCount <= 0, uses runtime.NumCPU().
// Returns the pool so callers can register task handlers.
func (s *Scheduler) InitCPUPool(workerCount int) *CPUWorkerPool {
	if workerCount <= 0 {
		workerCount = runtime.NumCPU()
	}

	s.mu.Lock()

	pool := NewCPUWorkerPool(CPUWorkerPoolConfig{
		Name:        "cpu",
		WorkerCount: workerCount,
		Logger:      s.logger,
	})
	pool.init(s.results)

	s.cpuPool = pool
	s.pools["cpu"] = pool
	running := s.running
	ctx := s.ctx
	s.mu.Unlock()

	s.logger.Debug("initialized CPU pool", "workers", workerCount)

	// If scheduler already running, start pool immediately.
	if running {
		if ctx == nil {
			ctx = context.Background()
		}
		go pool.Start(ctx)
		s.logger.Debug("cpu pool started after scheduler already running", "workers", workerCount)
	}
	return pool
}

// RegisterCPUHandler registers a task handler on the CPU pool.
func (s *Scheduler) RegisterCPUHandler(taskName string, handler CPUTaskHandler) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	if s.cpuPool != nil {
		s.cpuPool.RegisterHandler(taskName, handler)
		s.logger.Debug("registered CPU handler", "task", taskName)
	}
}

// GetPool returns a pool by name.
func (s *Scheduler) GetPool(name string) (WorkerPool, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	p, ok := s.pools[name]
	return p, ok
}

// ListPools returns all pool names.
func (s *Scheduler) ListPools() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	names := make([]string, 0, len(s.pools))
	for name := range s.pools {
		names = append(names, name)
	}
	return names
}
