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


var metricsCmd = &cobra.Command{
	Use:   "metrics",
	Short: "Metrics and cost tracking commands",
}

var settingsCmd = &cobra.Command{
	Use:   "settings",
	Short: "Configuration settings commands",
}

var llmcallsCmd = &cobra.Command{
	Use:   "llmcalls",
	Short: "LLM call history commands",
}

var voicesCmd = &cobra.Command{
	Use:   "voices",
	Short: "TTS voice management commands",
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
	jobsCmd.AddCommand((&endpoints.DeleteJobEndpoint{}).Command(getServerURL))
	jobsCmd.AddCommand((&endpoints.StartJobEndpoint{}).Command(getServerURL))
	jobsCmd.AddCommand((&endpoints.JobStatusEndpoint{}).Command(getServerURL))

	// Books as subcommand group
	booksCmd.AddCommand((&endpoints.IngestEndpoint{}).Command(getServerURL))
	booksCmd.AddCommand((&endpoints.ListBooksEndpoint{}).Command(getServerURL))
	booksCmd.AddCommand((&endpoints.GetBookEndpoint{}).Command(getServerURL))

	// Metrics as subcommand group
	metricsCmd.AddCommand((&endpoints.ListMetricsEndpoint{}).Command(getServerURL))
	metricsCmd.AddCommand((&endpoints.MetricsCostEndpoint{}).Command(getServerURL))
	metricsCmd.AddCommand((&endpoints.MetricsSummaryEndpoint{}).Command(getServerURL))

	// Add book cost to books group
	booksCmd.AddCommand((&endpoints.BookCostEndpoint{}).Command(getServerURL))

	// Audio commands
	booksCmd.AddCommand((&endpoints.GenerateAudioEndpoint{}).Command(getServerURL))
	booksCmd.AddCommand((&endpoints.GetAudioStatusEndpoint{}).Command(getServerURL))
	booksCmd.AddCommand((&endpoints.DownloadChapterAudioEndpoint{}).Command(getServerURL))

	// TTS config at top level
	apiCmd.AddCommand((&endpoints.GetTTSConfigEndpoint{}).Command(getServerURL))

	// Settings as subcommand group
	settingsCmd.AddCommand((&endpoints.ListSettingsEndpoint{}).Command(getServerURL))
	settingsCmd.AddCommand((&endpoints.GetSettingEndpoint{}).Command(getServerURL))
	settingsCmd.AddCommand((&endpoints.UpdateSettingEndpoint{}).Command(getServerURL))
	settingsCmd.AddCommand((&endpoints.ResetSettingEndpoint{}).Command(getServerURL))

	// LLM calls as subcommand group
	llmcallsCmd.AddCommand((&endpoints.ListLLMCallsEndpoint{}).Command(getServerURL))
	llmcallsCmd.AddCommand((&endpoints.GetLLMCallEndpoint{}).Command(getServerURL))
	llmcallsCmd.AddCommand((&endpoints.LLMCallCountsEndpoint{}).Command(getServerURL))

	// Voices as subcommand group
	voicesCmd.AddCommand((&endpoints.ListVoicesEndpoint{}).Command(getServerURL))
	voicesCmd.AddCommand((&endpoints.CreateVoiceEndpoint{}).Command(getServerURL))
	voicesCmd.AddCommand((&endpoints.SyncVoicesEndpoint{}).Command(getServerURL))
	voicesCmd.AddCommand((&endpoints.SetDefaultVoiceEndpoint{}).Command(getServerURL))
	voicesCmd.AddCommand((&endpoints.DeleteVoiceEndpoint{}).Command(getServerURL))

	apiCmd.AddCommand(jobsCmd)
	apiCmd.AddCommand(booksCmd)
	apiCmd.AddCommand(metricsCmd)
	apiCmd.AddCommand(settingsCmd)
	apiCmd.AddCommand(llmcallsCmd)
	apiCmd.AddCommand(voicesCmd)
	rootCmd.AddCommand(apiCmd)
}
