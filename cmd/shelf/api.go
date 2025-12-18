package main

import (
	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/server/endpoints"
)

var serverURL string

var apiCmd = &cobra.Command{
	Use:   "api",
	Short: "Commands that call the running server",
	Long: `API commands call the running Shelf server via HTTP.

These commands require a running server (shelf serve).
Use --server to specify a custom server URL.

Examples:
  shelf api health              # Check server health
  shelf api jobs list           # List all jobs
  shelf api jobs get <id>       # Get a specific job`,
}

var jobsCmd = &cobra.Command{
	Use:   "jobs",
	Short: "Job management commands",
}

var booksCmd = &cobra.Command{
	Use:   "books",
	Short: "Book management commands",
}

var pipelineCmd = &cobra.Command{
	Use:   "pipeline",
	Short: "Pipeline processing commands",
}

var metricsCmd = &cobra.Command{
	Use:   "metrics",
	Short: "Metrics and cost tracking commands",
}

// getServerURL returns the server URL at runtime (after flag parsing).
func getServerURL() string {
	return serverURL
}

func init() {
	// Add --server flag to api command (persistent so all subcommands inherit it)
	apiCmd.PersistentFlags().StringVar(
		&serverURL, "server", "http://localhost:8080", "Server URL",
	)

	// Health endpoints at top level of api
	apiCmd.AddCommand((&endpoints.HealthEndpoint{}).Command(getServerURL))
	apiCmd.AddCommand((&endpoints.ReadyEndpoint{}).Command(getServerURL))
	apiCmd.AddCommand((&endpoints.StatusEndpoint{}).Command(getServerURL))

	// Jobs as subcommand group
	jobsCmd.AddCommand((&endpoints.CreateJobEndpoint{}).Command(getServerURL))
	jobsCmd.AddCommand((&endpoints.ListJobsEndpoint{}).Command(getServerURL))
	jobsCmd.AddCommand((&endpoints.GetJobEndpoint{}).Command(getServerURL))
	jobsCmd.AddCommand((&endpoints.UpdateJobEndpoint{}).Command(getServerURL))

	// Books as subcommand group
	booksCmd.AddCommand((&endpoints.IngestEndpoint{}).Command(getServerURL))
	booksCmd.AddCommand((&endpoints.ListBooksEndpoint{}).Command(getServerURL))
	booksCmd.AddCommand((&endpoints.GetBookEndpoint{}).Command(getServerURL))

	// Pipeline as subcommand group
	pipelineCmd.AddCommand((&endpoints.StartPipelineEndpoint{}).Command(getServerURL))
	pipelineCmd.AddCommand((&endpoints.PipelineStatusEndpoint{}).Command(getServerURL))

	// Metrics as subcommand group
	metricsCmd.AddCommand((&endpoints.ListMetricsEndpoint{}).Command(getServerURL))
	metricsCmd.AddCommand((&endpoints.MetricsCostEndpoint{}).Command(getServerURL))
	metricsCmd.AddCommand((&endpoints.MetricsSummaryEndpoint{}).Command(getServerURL))

	// Add book cost to books group
	booksCmd.AddCommand((&endpoints.BookCostEndpoint{}).Command(getServerURL))

	apiCmd.AddCommand(jobsCmd)
	apiCmd.AddCommand(booksCmd)
	apiCmd.AddCommand(pipelineCmd)
	apiCmd.AddCommand(metricsCmd)
	rootCmd.AddCommand(apiCmd)
}
