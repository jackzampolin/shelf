package endpoints

import (
	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs/process_pages"
)

// Config holds dependencies needed by some endpoints.
type Config struct {
	DefraManager       *defra.DockerManager
	ProcessPagesConfig process_pages.Config
	SwaggerSpecPath    string
}

// All returns all endpoint instances.
func All(cfg Config) []api.Endpoint {
	return []api.Endpoint{
		// Health endpoints
		&HealthEndpoint{},
		&ReadyEndpoint{},
		&StatusEndpoint{DefraManager: cfg.DefraManager},

		// Job endpoints
		&CreateJobEndpoint{},
		&ListJobsEndpoint{},
		&GetJobEndpoint{},
		&UpdateJobEndpoint{},
		&DeleteJobEndpoint{},

		// Book endpoints
		&IngestEndpoint{},
		&UploadIngestEndpoint{},
		&ListBooksEndpoint{},
		&GetBookEndpoint{},
		&RerunTocEndpoint{ProcessPagesConfig: cfg.ProcessPagesConfig},

		// Page endpoints
		&PageImageEndpoint{},
		&ListPagesEndpoint{},
		&GetPageEndpoint{},

		// Job start/status endpoints
		&StartJobEndpoint{ProcessPagesConfig: cfg.ProcessPagesConfig},
		&JobStatusEndpoint{},
		&DetailedJobStatusEndpoint{},

		// Agent log endpoints
		&ListAgentLogsEndpoint{},
		&GetAgentLogEndpoint{},

		// Metrics endpoints
		&ListMetricsEndpoint{},
		&MetricsCostEndpoint{},
		&MetricsSummaryEndpoint{},
		&BookCostEndpoint{},

		// Settings endpoints
		&ListSettingsEndpoint{},
		&GetSettingEndpoint{},
		&UpdateSettingEndpoint{},
		&ResetSettingEndpoint{},

		// Swagger/OpenAPI endpoints
		&SwaggerEndpoint{SpecPath: cfg.SwaggerSpecPath},
		&SwaggerUIEndpoint{},

		// Static files (catch-all, must be last)
		&StaticEndpoint{},
	}
}

// JobCommands returns a cobra command tree for job operations.
// This groups job-related commands under "jobs" subcommand.
func JobCommands(serverURL string) []api.Endpoint {
	return []api.Endpoint{
		&CreateJobEndpoint{},
		&ListJobsEndpoint{},
		&GetJobEndpoint{},
		&UpdateJobEndpoint{},
		&DeleteJobEndpoint{},
	}
}

// SettingsCommands returns endpoints for settings operations.
// This groups settings-related commands under "settings" subcommand.
func SettingsCommands() []api.Endpoint {
	return []api.Endpoint{
		&ListSettingsEndpoint{},
		&GetSettingEndpoint{},
		&UpdateSettingEndpoint{},
		&ResetSettingEndpoint{},
	}
}
