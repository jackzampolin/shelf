// Shelf API
//
//	@title			Shelf API
//	@version		1.0
//	@description	Book digitization pipeline API for managing books, jobs, and processing.
//
//	@contact.name	API Support
//	@contact.url	https://github.com/jackzampolin/shelf
//
//	@license.name	MIT
//	@license.url	https://opensource.org/licenses/MIT
//
//	@host		localhost:8080
//	@BasePath	/
package main

import (
	"log/slog"
	"os"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/config"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/server"
)

var (
	serveHost string
	servePort string
)

var serveCmd = &cobra.Command{
	Use:   "serve",
	Short: "Start the Shelf server",
	Long: `Start the Shelf HTTP server.

This starts both the HTTP API server and the DefraDB container.
When the server shuts down (via Ctrl+C or SIGTERM), DefraDB is also stopped.

The server provides:
  - /health - Basic server health check
  - /ready  - Readiness check (includes DefraDB status)

Examples:
  shelf serve                    # Start on default port 8080
  shelf serve --port 3000        # Start on custom port
  shelf serve --host 0.0.0.0     # Bind to all interfaces`,
	RunE: func(cmd *cobra.Command, args []string) error {
		ctx := cmd.Context()

		// Set up logger with configured level
		logLvl := GetLogLevel()
		logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
			Level: logLvl,
		}))
		logger.Info("starting shelf server", "log_level", logLvl.String())

		// Get home directory
		h, err := home.New(homeDir)
		if err != nil {
			return err
		}
		if err := h.EnsureExists(); err != nil {
			return err
		}

		// Load configuration
		// Priority: --config flag > ./config.yaml > ~/.shelf/config.yaml
		configFile := cfgFile
		if configFile == "" {
			// Check local directory first
			if _, err := os.Stat("config.yaml"); err == nil {
				configFile = "config.yaml"
			} else {
				configFile = filepath.Join(h.Path(), "config.yaml")
			}
		}

		// Write default config if it doesn't exist
		if _, err := os.Stat(configFile); os.IsNotExist(err) {
			logger.Info("creating default config", "path", configFile)
			if err := config.WriteDefault(configFile); err != nil {
				logger.Warn("failed to write default config", "error", err)
			}
		}
		cfgMgr, err := config.NewManager(configFile)
		if err != nil {
			logger.Warn("config not loaded, using defaults", "error", err)
		} else {
			// Enable config hot-reload
			cfgMgr.WatchConfig()
			logger.Info("configuration loaded", "file", configFile)
		}

		// Ensure defradb data directory exists
		defraDataPath := filepath.Join(h.Path(), "defradb")
		if err := os.MkdirAll(defraDataPath, 0755); err != nil {
			return err
		}

		// Build DefraDB config from loaded config (if available)
		// HomePath enables deterministic container naming (shelf-defra-{hash})
		defraConfig := defra.DockerConfig{
			DataPath: defraDataPath,
			HomePath: h.Path(),
		}
		if cfgMgr != nil {
			cfg := cfgMgr.Get()
			if cfg.Defra.ContainerName != "" {
				defraConfig.ContainerName = cfg.Defra.ContainerName
			}
			if cfg.Defra.Image != "" {
				defraConfig.Image = cfg.Defra.Image
			}
			if cfg.Defra.Port != "" {
				defraConfig.HostPort = cfg.Defra.Port
			}
		}

		// Create server
		// Note: Job configs are NOT passed here - they are read from DefraDB at runtime
		// This ensures UI settings changes take effect immediately when jobs are created
		srv, err := server.New(server.Config{
			Host:          serveHost,
			Port:          servePort,
			DefraDataPath: defraDataPath,
			DefraConfig:   defraConfig,
			ConfigManager: cfgMgr,
			Logger:        logger,
			Home:          h,
		})
		if err != nil {
			return err
		}

		// Start server (blocks until shutdown)
		return srv.Start(ctx)
	},
}

func init() {
	serveCmd.Flags().StringVar(&serveHost, "host", "127.0.0.1", "Host to bind to")
	serveCmd.Flags().StringVar(&servePort, "port", "8080", "Port to listen on")

	rootCmd.AddCommand(serveCmd)
}
