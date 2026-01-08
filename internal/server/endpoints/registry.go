package endpoints

import (
	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs/common_structure"
	"github.com/jackzampolin/shelf/internal/jobs/label_book"
	"github.com/jackzampolin/shelf/internal/jobs/link_toc"
	"github.com/jackzampolin/shelf/internal/jobs/metadata_book"
	"github.com/jackzampolin/shelf/internal/jobs/ocr_book"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/jobs/toc_book"
)

// Config holds dependencies needed by some endpoints.
type Config struct {
	DefraManager          *defra.DockerManager
	ProcessBookConfig     process_book.Config
	OcrBookConfig         ocr_book.Config
	LabelBookConfig       label_book.Config
	MetadataBookConfig    metadata_book.Config
	TocBookConfig         toc_book.Config
	LinkTocConfig         link_toc.Config
	CommonStructureConfig common_structure.Config
	SwaggerSpecPath       string
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
		&RerunTocEndpoint{ProcessBookConfig: cfg.ProcessBookConfig},

		// Page endpoints
		&PageImageEndpoint{},
		&ListPagesEndpoint{},
		&GetPageEndpoint{},

		// Job start/status endpoints
		&StartJobEndpoint{
			ProcessBookConfig:     cfg.ProcessBookConfig,
			OcrBookConfig:         cfg.OcrBookConfig,
			LabelBookConfig:       cfg.LabelBookConfig,
			MetadataBookConfig:    cfg.MetadataBookConfig,
			TocBookConfig:         cfg.TocBookConfig,
			LinkTocConfig:         cfg.LinkTocConfig,
			CommonStructureConfig: cfg.CommonStructureConfig,
		},
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

		// LLM call history endpoints
		&ListLLMCallsEndpoint{},
		&GetLLMCallEndpoint{},
		&LLMCallCountsEndpoint{},

		// Prompt endpoints
		&ListPromptsEndpoint{},
		&GetPromptEndpoint{},
		&ListBookPromptsEndpoint{},
		&GetBookPromptEndpoint{},
		&SetBookPromptEndpoint{},
		&ClearBookPromptEndpoint{},

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

// LLMCallCommands returns endpoints for LLM call history operations.
// This groups llmcall-related commands under "llmcalls" subcommand.
func LLMCallCommands() []api.Endpoint {
	return []api.Endpoint{
		&ListLLMCallsEndpoint{},
		&GetLLMCallEndpoint{},
		&LLMCallCountsEndpoint{},
	}
}
