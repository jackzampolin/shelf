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
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/ingest"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/label_book"
	"github.com/jackzampolin/shelf/internal/jobs/link_toc"
	"github.com/jackzampolin/shelf/internal/jobs/metadata_book"
	"github.com/jackzampolin/shelf/internal/jobs/ocr_book"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/jobs/toc_book"
	"github.com/jackzampolin/shelf/internal/llmcall"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/prompts"
	"github.com/jackzampolin/shelf/internal/prompts/blend"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/prompts/label"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/schema"
	"github.com/jackzampolin/shelf/internal/server/endpoints"
	"github.com/jackzampolin/shelf/internal/svcctx"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
)

// Server is the main Shelf HTTP server.
// It manages the DefraDB container lifecycle - starting it on server start
// and stopping it on server shutdown.
type Server struct {
	httpServer       *http.Server
	defraManager     *defra.DockerManager
	defraClient      *defra.Client
	defraSink        *defra.Sink
	jobManager       *jobs.Manager
	scheduler        *jobs.Scheduler
	registry    *providers.Registry
	configMgr      *config.Manager
	configStore    config.Store
	promptResolver *prompts.Resolver
	logger         *slog.Logger
	home           *home.Dir

	// processBookCfg is saved for job factory registration
	processBookCfg process_book.Config
	// ocrBookCfg is saved for job factory registration
	ocrBookCfg ocr_book.Config
	// labelBookCfg is saved for job factory registration
	labelBookCfg label_book.Config
	// metadataBookCfg is saved for job factory registration
	metadataBookCfg metadata_book.Config
	// tocBookCfg is saved for job factory registration
	tocBookCfg toc_book.Config
	// linkTocCfg is saved for job factory registration
	linkTocCfg link_toc.Config

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
	// Home is the shelf home directory
	Home *home.Dir
	// PipelineConfig configures the page processing pipeline
	PipelineConfig PipelineConfig
}

// PipelineConfig configures the page processing pipeline stages.
type PipelineConfig struct {
	// OcrProviders are the OCR providers to use (e.g., ["mistral", "paddle"])
	OcrProviders []string
	// BlendProvider is the LLM provider for blending OCR outputs
	BlendProvider string
	// LabelProvider is the LLM provider for labeling page structure
	LabelProvider string
	// MetadataProvider is the LLM provider for metadata extraction
	MetadataProvider string
	// TocProvider is the LLM provider for ToC operations
	TocProvider string
	// DebugAgents enables debug logging for agent executions
	DebugAgents bool
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

	// Save process book config for job factory registration
	processBookCfg := process_book.Config{
		OcrProviders:     cfg.PipelineConfig.OcrProviders,
		BlendProvider:    cfg.PipelineConfig.BlendProvider,
		LabelProvider:    cfg.PipelineConfig.LabelProvider,
		MetadataProvider: cfg.PipelineConfig.MetadataProvider,
		TocProvider:      cfg.PipelineConfig.TocProvider,
		DebugAgents:      cfg.PipelineConfig.DebugAgents,
	}

	// Save OCR book config for job factory registration (subset of process pages)
	ocrBookCfg := ocr_book.Config{
		OcrProviders:  cfg.PipelineConfig.OcrProviders,
		BlendProvider: cfg.PipelineConfig.BlendProvider,
	}

	// Save label book config for job factory registration
	labelBookCfg := label_book.Config{
		LabelProvider: cfg.PipelineConfig.LabelProvider,
	}

	// Save metadata book config for job factory registration
	metadataBookCfg := metadata_book.Config{
		MetadataProvider: cfg.PipelineConfig.MetadataProvider,
	}

	// Save toc book config for job factory registration
	tocBookCfg := toc_book.Config{
		TocProvider: cfg.PipelineConfig.TocProvider,
		DebugAgents: cfg.PipelineConfig.DebugAgents,
	}

	// Save link toc config for job factory registration
	linkTocCfg := link_toc.Config{
		TocProvider: cfg.PipelineConfig.TocProvider,
		DebugAgents: cfg.PipelineConfig.DebugAgents,
	}

	s := &Server{
		defraManager:     defraManager,
		registry:         registry,
		processBookCfg:   processBookCfg,
		ocrBookCfg:       ocrBookCfg,
		labelBookCfg:     labelBookCfg,
		metadataBookCfg:  metadataBookCfg,
		tocBookCfg:       tocBookCfg,
		linkTocCfg:       linkTocCfg,
		configMgr:       cfg.ConfigManager,
		logger:          cfg.Logger,
		home:            cfg.Home,
	}

	// Create endpoint registry and register all endpoints
	s.endpointRegistry = api.NewRegistry()
	for _, ep := range endpoints.All(endpoints.Config{
		DefraManager:       defraManager,
		ProcessBookConfig:  processBookCfg,
		OcrBookConfig:       ocrBookCfg,
		LabelBookConfig:     labelBookCfg,
		MetadataBookConfig:  metadataBookCfg,
		TocBookConfig:       tocBookCfg,
	}) {
		s.endpointRegistry.Register(ep)
	}

	// Set up HTTP server
	mux := http.NewServeMux()
	s.endpointRegistry.RegisterRoutes(mux, s.requireInit)

	s.httpServer = &http.Server{
		Addr:         net.JoinHostPort(cfg.Host, cfg.Port),
		Handler:      s.withLogging(s.withServices(mux)),
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 10 * time.Minute, // Long timeout for large file operations
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

	// Create config store and seed defaults
	s.configStore = config.NewStore(s.defraClient)
	s.logger.Info("seeding config defaults")
	if err := config.SeedDefaults(ctx, s.configStore, s.logger); err != nil {
		_ = s.shutdown()
		return fmt.Errorf("config seeding failed: %w", err)
	}

	// Create prompt resolver and register all embedded prompts
	promptStore := prompts.NewStore(s.defraClient, s.logger)
	s.promptResolver = prompts.NewResolver(promptStore, s.logger)
	blend.RegisterPrompts(s.promptResolver)
	label.RegisterPrompts(s.promptResolver)
	metadata.RegisterPrompts(s.promptResolver)
	extract_toc.RegisterPrompts(s.promptResolver)
	toc_finder.RegisterPrompts(s.promptResolver)
	toc_entry_finder.RegisterPrompts(s.promptResolver)

	// Sync prompts to database (creates new, updates modified)
	s.logger.Info("syncing prompts to database")
	if err := s.promptResolver.SyncAll(ctx); err != nil {
		_ = s.shutdown()
		return fmt.Errorf("prompt seeding failed: %w", err)
	}

	// Create job manager
	s.jobManager = jobs.NewManager(s.defraClient, s.logger)

	// Create write sink for batched DefraDB writes
	s.defraSink = defra.NewSink(defra.SinkConfig{
		Client: s.defraClient,
		Logger: s.logger,
	})
	s.defraSink.Start(ctx)

	// Create scheduler for job execution (sink enables fire-and-forget metrics)
	s.scheduler = jobs.NewScheduler(jobs.SchedulerConfig{
		Manager: s.jobManager,
		Logger:  s.logger,
		Sink:    s.defraSink,
	})

	// Initialize workers from provider registry
	if err := s.scheduler.InitFromRegistry(s.registry); err != nil {
		_ = s.shutdown()
		return fmt.Errorf("failed to initialize workers: %w", err)
	}

	// Initialize CPU pool for CPU-bound tasks (uses runtime.NumCPU())
	s.scheduler.InitCPUPool(0)

	// Register CPU task handlers
	s.scheduler.RegisterCPUHandler(ingest.TaskExtractPage, ingest.ExtractPageHandler())

	// Register job factories for resumption
	s.scheduler.RegisterFactory(process_book.JobType, process_book.JobFactory(s.processBookCfg))
	s.scheduler.RegisterFactory(ocr_book.JobType, ocr_book.JobFactory(s.ocrBookCfg))
	s.scheduler.RegisterFactory(label_book.JobType, label_book.JobFactory(s.labelBookCfg))
	s.scheduler.RegisterFactory(metadata_book.JobType, metadata_book.JobFactory(s.metadataBookCfg))
	s.scheduler.RegisterFactory(toc_book.JobType, toc_book.JobFactory(s.tocBookCfg))
	s.scheduler.RegisterFactory(link_toc.JobType, link_toc.JobFactory(s.linkTocCfg))

	// Start scheduler in background
	go s.scheduler.Start(ctx)

	// Create services struct for context enrichment
	s.services = &svcctx.Services{
		DefraClient:    s.defraClient,
		DefraSink:      s.defraSink,
		JobManager:     s.jobManager,
		Registry:       s.registry,
		Scheduler:      s.scheduler,
		ConfigStore:    s.configStore,
		Logger:         s.logger,
		Home:           s.home,
		MetricsQuery:   metrics.NewQuery(s.defraClient),
		LLMCallStore:   llmcall.NewStore(s.defraClient),
		PromptResolver: s.promptResolver,
	}

	// Pass services to scheduler for async job context injection
	s.scheduler.SetContextEnricher(func(ctx context.Context) context.Context {
		return svcctx.WithServices(ctx, s.services)
	})

	// Resume any interrupted jobs from previous run
	if resumed, err := s.scheduler.Resume(ctx); err != nil {
		s.logger.Warn("failed to resume jobs", "error", err)
	} else if resumed > 0 {
		s.logger.Info("resumed interrupted jobs", "count", resumed)
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

	// Stop write sink (flushes remaining writes)
	if s.defraSink != nil {
		s.logger.Info("stopping write sink")
		s.defraSink.Stop()
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

// withLogging wraps a handler to log requests.
func (s *Server) withLogging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		s.logger.Info("request started", "method", r.Method, "path", r.URL.Path)

		// Wrap response writer to capture status code
		wrapped := &statusWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(wrapped, r)

		s.logger.Info("request completed",
			"method", r.Method,
			"path", r.URL.Path,
			"status", wrapped.status,
			"duration", time.Since(start).String(),
		)
	})
}

// statusWriter wraps http.ResponseWriter to capture status code.
type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(status int) {
	w.status = status
	w.ResponseWriter.WriteHeader(status)
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
