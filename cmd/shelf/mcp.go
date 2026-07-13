package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/researchmcp"
	"github.com/jackzampolin/shelf/version"
)

var (
	mcpHost     string
	mcpPort     string
	mcpShelfURL string
)

var mcpCmd = &cobra.Command{
	Use:   "mcp",
	Short: "Serve bounded read-only research tools over MCP",
	RunE: func(cmd *cobra.Command, _ []string) error {
		addr := mcpHost + ":" + mcpPort
		server := &http.Server{
			Addr:              addr,
			Handler:           researchmcp.Handler(researchmcp.NewClient(mcpShelfURL, nil), version.GitRelease),
			ReadHeaderTimeout: 10 * time.Second,
			IdleTimeout:       2 * time.Minute,
		}
		done := make(chan error, 1)
		go func() {
			slog.Info("shelf research MCP listening", "addr", addr, "mcp_path", "/mcp", "shelf_url", mcpShelfURL)
			done <- server.ListenAndServe()
		}()
		select {
		case <-cmd.Context().Done():
			ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
			defer cancel()
			if err := server.Shutdown(ctx); err != nil {
				return err
			}
			return nil
		case err := <-done:
			if errors.Is(err, http.ErrServerClosed) {
				return nil
			}
			return fmt.Errorf("serve shelf research MCP: %w", err)
		}
	},
}

func init() {
	mcpCmd.Flags().StringVar(&mcpHost, "host", "127.0.0.1", "Host to bind to")
	mcpCmd.Flags().StringVar(&mcpPort, "port", "18081", "MCP HTTP port")
	mcpCmd.Flags().StringVar(&mcpShelfURL, "shelf-url", "http://127.0.0.1:18080", "Shelf API base URL")
	rootCmd.AddCommand(mcpCmd)
}
