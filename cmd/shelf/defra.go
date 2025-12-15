package main

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
)

var defraCmd = &cobra.Command{
	Use:   "defra",
	Short: "Manage the DefraDB container",
	Long: `Manage the DefraDB container lifecycle.

DefraDB is the source of truth for all pipeline state. The database runs
in a Docker container with data persisted to ~/.shelf/defradb/.

Examples:
  shelf defra start   # Start the DefraDB container
  shelf defra stop    # Stop the container (data preserved)
  shelf defra status  # Check container status
  shelf defra logs    # View container logs`,
}

var defraStartCmd = &cobra.Command{
	Use:   "start",
	Short: "Start the DefraDB container",
	Long: `Start the DefraDB container.

If the container doesn't exist, it will be created and started.
If it exists but is stopped, it will be started.
If it's already running, this is a no-op.

Data is persisted to ~/.shelf/defradb/.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		ctx := cmd.Context()

		h, err := getHome()
		if err != nil {
			return err
		}

		mgr, err := getDockerManager(h)
		if err != nil {
			return err
		}
		defer mgr.Close()

		fmt.Println("Starting DefraDB...")
		if err := mgr.Start(ctx); err != nil {
			return fmt.Errorf("failed to start DefraDB: %w", err)
		}

		fmt.Printf("DefraDB is running at %s\n", mgr.URL())
		return nil
	},
}

var defraStopCmd = &cobra.Command{
	Use:   "stop",
	Short: "Stop the DefraDB container",
	Long: `Stop the DefraDB container.

This stops the container but preserves data. Use 'shelf defra start'
to restart it later.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		ctx := cmd.Context()

		h, err := getHome()
		if err != nil {
			return err
		}

		mgr, err := getDockerManager(h)
		if err != nil {
			return err
		}
		defer mgr.Close()

		fmt.Println("Stopping DefraDB...")
		if err := mgr.Stop(ctx); err != nil {
			return fmt.Errorf("failed to stop DefraDB: %w", err)
		}

		fmt.Println("DefraDB stopped")
		return nil
	},
}

var defraStatusCmd = &cobra.Command{
	Use:   "status",
	Short: "Show DefraDB container status",
	RunE: func(cmd *cobra.Command, args []string) error {
		ctx := cmd.Context()

		h, err := getHome()
		if err != nil {
			return err
		}

		mgr, err := getDockerManager(h)
		if err != nil {
			return err
		}
		defer mgr.Close()

		status, err := mgr.Status(ctx)
		if err != nil {
			return fmt.Errorf("failed to get status: %w", err)
		}

		switch status {
		case defra.StatusRunning:
			fmt.Printf("Status: %s\n", status)
			fmt.Printf("URL: %s\n", mgr.URL())

			// Try health check
			client := defra.NewClient(mgr.URL())
			if err := client.HealthCheck(ctx); err != nil {
				fmt.Printf("Health: unhealthy (%v)\n", err)
			} else {
				fmt.Println("Health: healthy")
			}
		case defra.StatusStopped:
			fmt.Printf("Status: %s (use 'shelf defra start' to start)\n", status)
		case defra.StatusNotFound:
			fmt.Printf("Status: %s (use 'shelf defra start' to create)\n", status)
		default:
			fmt.Printf("Status: %s\n", status)
		}

		return nil
	},
}

var (
	logsTail   string
	logsFollow bool
)

var defraLogsCmd = &cobra.Command{
	Use:   "logs",
	Short: "Show DefraDB container logs",
	RunE: func(cmd *cobra.Command, args []string) error {
		ctx := cmd.Context()

		h, err := getHome()
		if err != nil {
			return err
		}

		mgr, err := getDockerManager(h)
		if err != nil {
			return err
		}
		defer mgr.Close()

		logs, err := mgr.Logs(ctx, logsTail)
		if err != nil {
			return fmt.Errorf("failed to get logs: %w", err)
		}

		fmt.Print(logs)
		return nil
	},
}

var defraRemoveCmd = &cobra.Command{
	Use:   "remove",
	Short: "Remove the DefraDB container",
	Long: `Remove the DefraDB container.

This stops and removes the container. Data in ~/.shelf/defradb/
is NOT deleted - only the container is removed.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		ctx := cmd.Context()

		h, err := getHome()
		if err != nil {
			return err
		}

		mgr, err := getDockerManager(h)
		if err != nil {
			return err
		}
		defer mgr.Close()

		fmt.Println("Removing DefraDB container...")
		if err := mgr.Remove(ctx); err != nil {
			return fmt.Errorf("failed to remove container: %w", err)
		}

		fmt.Println("DefraDB container removed (data preserved)")
		return nil
	},
}

var defraWaitCmd = &cobra.Command{
	Use:   "wait",
	Short: "Wait for DefraDB to be ready",
	Long: `Wait for DefraDB to be ready to accept connections.

This is useful in scripts to ensure DefraDB is fully started
before running other commands.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		ctx := cmd.Context()

		h, err := getHome()
		if err != nil {
			return err
		}

		mgr, err := getDockerManager(h)
		if err != nil {
			return err
		}
		defer mgr.Close()

		timeout, _ := cmd.Flags().GetDuration("timeout")
		fmt.Printf("Waiting for DefraDB (timeout: %s)...\n", timeout)

		if err := mgr.WaitReady(ctx, timeout); err != nil {
			return fmt.Errorf("DefraDB not ready: %w", err)
		}

		fmt.Println("DefraDB is ready")
		return nil
	},
}

func init() {
	// Add subcommands
	defraCmd.AddCommand(defraStartCmd)
	defraCmd.AddCommand(defraStopCmd)
	defraCmd.AddCommand(defraStatusCmd)
	defraCmd.AddCommand(defraLogsCmd)
	defraCmd.AddCommand(defraRemoveCmd)
	defraCmd.AddCommand(defraWaitCmd)

	// Logs flags
	defraLogsCmd.Flags().StringVar(&logsTail, "tail", "100", "Number of lines to show from the end")
	defraLogsCmd.Flags().BoolVarP(&logsFollow, "follow", "f", false, "Follow log output (not yet implemented)")

	// Wait flags
	defraWaitCmd.Flags().Duration("timeout", 30*time.Second, "Timeout waiting for DefraDB")

	// Add to root
	rootCmd.AddCommand(defraCmd)
}

// getHome returns the home directory manager.
func getHome() (*home.Dir, error) {
	h, err := home.New(homeDir)
	if err != nil {
		return nil, err
	}
	if err := h.EnsureExists(); err != nil {
		return nil, fmt.Errorf("failed to create home directory: %w", err)
	}
	return h, nil
}

// getDockerManager creates a DockerManager with the standard config.
func getDockerManager(h *home.Dir) (*defra.DockerManager, error) {
	dataPath := filepath.Join(h.Path(), "defradb")

	// Ensure data directory exists
	if err := os.MkdirAll(dataPath, 0755); err != nil {
		return nil, fmt.Errorf("failed to create data directory: %w", err)
	}

	return defra.NewDockerManager(defra.DockerConfig{
		DataPath: dataPath,
	})
}
