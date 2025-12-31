// Package svcctx provides service context for dependency injection via context.
// This package is separate from server to avoid import cycles with endpoints.
package svcctx

import (
	"context"
	"log/slog"

	"github.com/jackzampolin/shelf/internal/config"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/llmcall"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/providers"
)

// Services holds all core services that flow through context.
// Components extract what they need via the individual extractors.
type Services struct {
	DefraClient  *defra.Client
	DefraSink    *defra.Sink
	JobManager   *jobs.Manager
	Registry     *providers.Registry
	Scheduler    *jobs.Scheduler
	ConfigStore  config.Store
	Logger       *slog.Logger
	Home         *home.Dir
	MetricsQuery *metrics.Query
	LLMCallStore *llmcall.Store
}

type servicesKey struct{}

// WithServices returns a new context with services attached.
func WithServices(ctx context.Context, s *Services) context.Context {
	return context.WithValue(ctx, servicesKey{}, s)
}

// ServicesFrom extracts the full Services struct from context.
// Returns nil if not present.
func ServicesFrom(ctx context.Context) *Services {
	s, _ := ctx.Value(servicesKey{}).(*Services)
	return s
}

// DefraClientFrom extracts the DefraDB client from context.
func DefraClientFrom(ctx context.Context) *defra.Client {
	if s := ServicesFrom(ctx); s != nil {
		return s.DefraClient
	}
	return nil
}

// DefraSinkFrom extracts the DefraDB write sink from context.
func DefraSinkFrom(ctx context.Context) *defra.Sink {
	if s := ServicesFrom(ctx); s != nil {
		return s.DefraSink
	}
	return nil
}

// JobManagerFrom extracts the job manager from context.
func JobManagerFrom(ctx context.Context) *jobs.Manager {
	if s := ServicesFrom(ctx); s != nil {
		return s.JobManager
	}
	return nil
}

// RegistryFrom extracts the provider registry from context.
func RegistryFrom(ctx context.Context) *providers.Registry {
	if s := ServicesFrom(ctx); s != nil {
		return s.Registry
	}
	return nil
}

// SchedulerFrom extracts the scheduler from context.
func SchedulerFrom(ctx context.Context) *jobs.Scheduler {
	if s := ServicesFrom(ctx); s != nil {
		return s.Scheduler
	}
	return nil
}

// LoggerFrom extracts the logger from context.
func LoggerFrom(ctx context.Context) *slog.Logger {
	if s := ServicesFrom(ctx); s != nil {
		return s.Logger
	}
	return nil
}

// HomeFrom extracts the home directory from context.
func HomeFrom(ctx context.Context) *home.Dir {
	if s := ServicesFrom(ctx); s != nil {
		return s.Home
	}
	return nil
}

// ConfigStoreFrom extracts the config store from context.
func ConfigStoreFrom(ctx context.Context) config.Store {
	if s := ServicesFrom(ctx); s != nil {
		return s.ConfigStore
	}
	return nil
}

// MetricsQueryFrom extracts the metrics query helper from context.
func MetricsQueryFrom(ctx context.Context) *metrics.Query {
	if s := ServicesFrom(ctx); s != nil {
		return s.MetricsQuery
	}
	return nil
}

// LLMCallStoreFrom extracts the LLM call store from context.
func LLMCallStoreFrom(ctx context.Context) *llmcall.Store {
	if s := ServicesFrom(ctx); s != nil {
		return s.LLMCallStore
	}
	return nil
}
