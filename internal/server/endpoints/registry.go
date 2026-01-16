package endpoints

import (
	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
)

// Config holds dependencies needed by some endpoints.
// Job configs are no longer stored here - they are read from DefraDB at request time.
type Config struct {
	DefraManager    *defra.DockerManager
	SwaggerSpecPath string
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
		&GetBookChaptersEndpoint{},
		&RerunTocEndpoint{},

		// Export endpoints
		&ExportEpubEndpoint{},
		&DownloadEpubEndpoint{},
		&ExportStorytellerEndpoint{},
		&DownloadStorytellerEndpoint{},

		// Audio endpoints
		&GenerateAudioEndpoint{},
		&GetAudioStatusEndpoint{},
		&DownloadChapterAudioEndpoint{},

		// TTS configuration
		&GetTTSConfigEndpoint{},

		// Voice endpoints
		&ListVoicesEndpoint{},
		&CreateVoiceEndpoint{},
		&SyncVoicesEndpoint{},
		&SetDefaultVoiceEndpoint{},
		&DeleteVoiceEndpoint{},

		// Page endpoints
		&PageImageEndpoint{},
		&ListPagesEndpoint{},
		&GetPageEndpoint{},

		// Job start/status endpoints
		&StartJobEndpoint{},
		&JobStatusEndpoint{},
		&DetailedJobStatusEndpoint{},

		// Agent log endpoints
		&ListAgentLogsEndpoint{},
		&GetAgentLogEndpoint{},

		// Metrics endpoints
		&ListMetricsEndpoint{},
		&MetricsCostEndpoint{},
		&MetricsSummaryEndpoint{},
		&MetricsDetailedEndpoint{},
		&BookCostEndpoint{},
		&BookMetricsDetailedEndpoint{},

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

// VoiceCommands returns endpoints for voice management operations.
// This groups voice-related commands under "voices" subcommand.
func VoiceCommands() []api.Endpoint {
	return []api.Endpoint{
		&ListVoicesEndpoint{},
		&CreateVoiceEndpoint{},
		&SyncVoicesEndpoint{},
		&SetDefaultVoiceEndpoint{},
		&DeleteVoiceEndpoint{},
	}
}
