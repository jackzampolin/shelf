package main

import (
	"log/slog"
	"os"
	"path/filepath"

	"github.com/spf13/cobra"

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

		// Set up logger
		logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
			Level: slog.LevelInfo,
		}))

		// Get home directory
		h, err := home.New(homeDir)
		if err != nil {
			return err
		}
		if err := h.EnsureExists(); err != nil {
			return err
		}

		// Ensure defradb data directory exists
		defraDataPath := filepath.Join(h.Path(), "defradb")
		if err := os.MkdirAll(defraDataPath, 0755); err != nil {
			return err
		}

		// Create server
		srv, err := server.New(server.Config{
			Host:          serveHost,
			Port:          servePort,
			DefraDataPath: defraDataPath,
			DefraConfig: defra.DockerConfig{
				// Use defaults from defra package
			},
			Logger: logger,
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
