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

	"github.com/jackzampolin/shelf/internal/config"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/schema"
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
		provCfg := cfg.ConfigManager.Get().ToProviderRegistryConfig()
		registry.Reload(configToRegistryConfig(provCfg))

		// Watch for config changes
		cfg.ConfigManager.OnChange(func(c *config.Config) {
			provCfg := c.ToProviderRegistryConfig()
			registry.Reload(configToRegistryConfig(provCfg))
			cfg.Logger.Info("provider registry reloaded from config")
		})
	}

	s := &Server{
		defraManager: defraManager,
		registry:     registry,
		configMgr:    cfg.ConfigManager,
		logger:       cfg.Logger,
	}

	// Set up HTTP server
	mux := http.NewServeMux()
	s.registerRoutes(mux)

	s.httpServer = &http.Server{
		Addr:         net.JoinHostPort(cfg.Host, cfg.Port),
		Handler:      mux,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	return s, nil
}

// configToRegistryConfig converts config.ProviderRegistryConfig to providers.RegistryConfig.
func configToRegistryConfig(cfg config.ProviderRegistryConfig) providers.RegistryConfig {
	result := providers.RegistryConfig{
		OCRProviders: make(map[string]providers.OCRProviderConfig),
		LLMProviders: make(map[string]providers.LLMProviderConfig),
	}

	for name, ocr := range cfg.OCRProviders {
		result.OCRProviders[name] = providers.OCRProviderConfig{
			Type:      ocr.Type,
			Model:     ocr.Model,
			APIKey:    ocr.APIKey,
			RateLimit: ocr.RateLimit,
			Enabled:   ocr.Enabled,
		}
	}

	for name, llm := range cfg.LLMProviders {
		result.LLMProviders[name] = providers.LLMProviderConfig{
			Type:      llm.Type,
			Model:     llm.Model,
			APIKey:    llm.APIKey,
			RateLimit: llm.RateLimit,
			Enabled:   llm.Enabled,
		}
	}

	return result
}

// Start starts the server and DefraDB.
// It blocks until the context is cancelled or an error occurs.
// Any existing DefraDB container is removed first to ensure a clean start.
func (s *Server) Start(ctx context.Context) error {
	s.mu.Lock()
	if s.running {
		s.mu.Unlock()
		return errors.New("server already running")
	}
	s.running = true
	s.mu.Unlock()

	// Remove any existing container for a clean start
	s.logger.Info("cleaning up existing DefraDB container")
	if err := s.defraManager.Remove(ctx); err != nil {
		s.logger.Warn("failed to remove existing container", "error", err)
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
