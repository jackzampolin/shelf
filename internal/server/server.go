package server

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"sync"
	"time"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/config"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/schema"
	"github.com/jackzampolin/shelf/internal/server/endpoints"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// Server is the main Shelf HTTP server.
// It manages the DefraDB container lifecycle - starting it on server start
// and stopping it on server shutdown.
type Server struct {
	httpServer   *http.Server
	defraManager *defra.DockerManager
	defraClient  *defra.Client
	jobManager   *jobs.Manager
	registry     *providers.Registry
	configMgr    *config.Manager
	logger       *slog.Logger

	// services holds all core services for context enrichment
	services *svcctx.Services

	// endpoints registry for HTTP routes
	endpointRegistry *api.Registry

	mu      sync.RWMutex
	running bool
}

// Config holds server configuration.
type Config struct {
	// Host is the address to bind to (default: 127.0.0.1)
	Host string
	// Port is the port to listen on (default: 8080)
	Port string
	// DefraDataPath is the path to persist DefraDB data
	DefraDataPath string
	// DefraConfig holds DefraDB container settings
	DefraConfig defra.DockerConfig
	// ConfigManager provides configuration with hot-reload support
	ConfigManager *config.Manager
	// Logger is the structured logger to use
	Logger *slog.Logger
}

// New creates a new Server with the given configuration.
func New(cfg Config) (*Server, error) {
	if cfg.Host == "" {
		cfg.Host = "127.0.0.1"
	}
	if cfg.Port == "" {
		cfg.Port = "8080"
	}
	if cfg.Logger == nil {
		cfg.Logger = slog.Default()
	}

	// Set up DefraDB data path
	if cfg.DefraDataPath != "" {
		cfg.DefraConfig.DataPath = cfg.DefraDataPath
	}

	defraManager, err := defra.NewDockerManager(cfg.DefraConfig)
	if err != nil {
		return nil, fmt.Errorf("failed to create defra manager: %w", err)
	}

	// Create provider registry
	registry := providers.NewRegistry()
	registry.SetLogger(cfg.Logger)

	// If config manager provided, set up providers and hot reload
	if cfg.ConfigManager != nil {
		registry.Reload(cfg.ConfigManager.Get().ToProviderRegistryConfig())

		// Watch for config changes
		cfg.ConfigManager.OnChange(func(c *config.Config) {
			registry.Reload(c.ToProviderRegistryConfig())
			cfg.Logger.Info("provider registry reloaded from config")
		})
	}

	s := &Server{
		defraManager: defraManager,
		registry:     registry,
		configMgr:    cfg.ConfigManager,
		logger:       cfg.Logger,
	}

	// Create endpoint registry and register all endpoints
	s.endpointRegistry = api.NewRegistry()
	for _, ep := range endpoints.All(endpoints.Config{DefraManager: defraManager}) {
		s.endpointRegistry.Register(ep)
	}

	// Set up HTTP server
	mux := http.NewServeMux()
	s.endpointRegistry.RegisterRoutes(mux, s.requireInit)

	s.httpServer = &http.Server{
		Addr:         net.JoinHostPort(cfg.Host, cfg.Port),
		Handler:      s.withServices(mux),
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	return s, nil
}

// Start starts the server and DefraDB.
// It blocks until the context is cancelled or an error occurs.
// If an existing DefraDB container exists, it validates the configuration matches.
func (s *Server) Start(ctx context.Context) error {
	s.mu.Lock()
	if s.running {
		s.mu.Unlock()
		return errors.New("server already running")
	}
	s.running = true
	s.mu.Unlock()

	// Validate any existing container matches our config
	if err := s.defraManager.ValidateExisting(ctx); err != nil {
		s.setNotRunning()
		return fmt.Errorf("existing DefraDB container incompatible: %w", err)
	}

	// Start DefraDB
	s.logger.Info("starting DefraDB")
	if err := s.defraManager.Start(ctx); err != nil {
		s.setNotRunning()
		return fmt.Errorf("failed to start DefraDB: %w", err)
	}

	// Create client after DefraDB is up
	s.defraClient = defra.NewClient(s.defraManager.URL())

	// Verify DefraDB is healthy
	if err := s.defraClient.HealthCheck(ctx); err != nil {
		_ = s.shutdown() // Clean up DefraDB on failure
		return fmt.Errorf("DefraDB health check failed: %w", err)
	}
	s.logger.Info("DefraDB is ready", "url", s.defraManager.URL())

	// Initialize schemas
	s.logger.Info("initializing schemas")
	if err := schema.Initialize(ctx, s.defraClient, s.logger); err != nil {
		_ = s.shutdown()
		return fmt.Errorf("schema initialization failed: %w", err)
	}

	// Create job manager
	s.jobManager = jobs.NewManager(s.defraClient, s.logger)

	// Create services struct for context enrichment
	s.services = &svcctx.Services{
		DefraClient: s.defraClient,
		JobManager:  s.jobManager,
		Registry:    s.registry,
		Logger:      s.logger,
	}

	// Start HTTP server in goroutine
	errCh := make(chan error, 1)
	go func() {
		s.logger.Info("starting HTTP server", "addr", s.httpServer.Addr)
		if err := s.httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
		close(errCh)
	}()

	// Wait for context cancellation or error
	select {
	case <-ctx.Done():
		s.logger.Info("shutdown signal received")
	case err := <-errCh:
		if err != nil {
			_ = s.shutdown() // Clean up DefraDB on HTTP error
			return fmt.Errorf("HTTP server error: %w", err)
		}
	}

	return s.shutdown()
}

// shutdown performs graceful shutdown of both HTTP server and DefraDB.
func (s *Server) shutdown() error {
	s.logger.Info("shutting down server")

	// Shutdown HTTP server with timeout
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := s.httpServer.Shutdown(shutdownCtx); err != nil {
		s.logger.Error("HTTP server shutdown error", "error", err)
	}

	// Stop DefraDB
	s.logger.Info("stopping DefraDB")
	if err := s.defraManager.Stop(shutdownCtx); err != nil {
		s.logger.Error("DefraDB stop error", "error", err)
	}

	// Close Docker client
	if err := s.defraManager.Close(); err != nil {
		s.logger.Error("DefraDB manager close error", "error", err)
	}

	s.setNotRunning()
	s.logger.Info("server stopped")
	return nil
}

func (s *Server) setNotRunning() {
	s.mu.Lock()
	s.running = false
	s.mu.Unlock()
}

// IsRunning returns whether the server is currently running.
func (s *Server) IsRunning() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.running
}

// DefraClient returns the DefraDB client.
// Returns nil if the server hasn't started yet.
func (s *Server) DefraClient() *defra.Client {
	return s.defraClient
}

// JobManager returns the job manager.
// Returns nil if the server hasn't started yet.
func (s *Server) JobManager() *jobs.Manager {
	return s.jobManager
}

// Addr returns the server's listen address.
func (s *Server) Addr() string {
	return s.httpServer.Addr
}

// Registry returns the provider registry.
func (s *Server) Registry() *providers.Registry {
	return s.registry
}

// withServices wraps a handler to enrich the request context with services.
func (s *Server) withServices(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		if s.services != nil {
			ctx = svcctx.WithServices(ctx, s.services)
		}
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// requireInit is middleware that ensures the server is fully initialized.
// Returns 503 Service Unavailable if DefraDB or job manager aren't ready.
func (s *Server) requireInit(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if s.defraClient == nil || s.jobManager == nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusServiceUnavailable)
			w.Write([]byte(`{"error":"server not fully initialized"}`))
			return
		}
		next(w, r)
	}
}
