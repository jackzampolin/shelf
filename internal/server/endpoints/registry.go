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
		&ListBooksEndpoint{},
		&GetBookEndpoint{},

		// Job start/status endpoints
		&StartJobEndpoint{ProcessPagesConfig: cfg.ProcessPagesConfig},
		&JobStatusEndpoint{},

		// Metrics endpoints
		&ListMetricsEndpoint{},
		&MetricsCostEndpoint{},
		&MetricsSummaryEndpoint{},
		&BookCostEndpoint{},
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
