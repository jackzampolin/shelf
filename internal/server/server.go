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

	"github.com/jackzampolin/shelf/internal/defra"
)

// Server is the main Shelf HTTP server.
// It manages the DefraDB container lifecycle - starting it on server start
// and stopping it on server shutdown.
type Server struct {
	httpServer   *http.Server
	defraManager *defra.DockerManager
	defraClient  *defra.Client
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

	s := &Server{
		defraManager: defraManager,
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

// Start starts the server and DefraDB.
// It blocks until the context is cancelled or an error occurs.
func (s *Server) Start(ctx context.Context) error {
	s.mu.Lock()
	if s.running {
		s.mu.Unlock()
		return errors.New("server already running")
	}
	s.running = true
	s.mu.Unlock()

	// Start DefraDB first
	s.logger.Info("starting DefraDB")
	if err := s.defraManager.Start(ctx); err != nil {
		s.setNotRunning()
		return fmt.Errorf("failed to start DefraDB: %w", err)
	}

	// Create client after DefraDB is up
	s.defraClient = defra.NewClient(s.defraManager.URL())

	// Verify DefraDB is healthy
	if err := s.defraClient.HealthCheck(ctx); err != nil {
		s.setNotRunning()
		return fmt.Errorf("DefraDB health check failed: %w", err)
	}
	s.logger.Info("DefraDB is ready", "url", s.defraManager.URL())

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

// Addr returns the server's listen address.
func (s *Server) Addr() string {
	return s.httpServer.Addr
}
