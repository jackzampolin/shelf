package endpoints

import (
	"github.com/jackzampolin/shelf/internal/api"
)

// Config holds dependencies needed by some endpoints.
// Job configs are no longer stored here - they are read from DefraDB at request time.
type Config struct {
	SwaggerSpecPath string
}

// All returns all endpoint instances.
func All(cfg Config) []api.Endpoint {
	return []api.Endpoint{
		// Health endpoints
		&HealthEndpoint{},
		&ReadyEndpoint{},
		&StatusEndpoint{},
		&RunSummaryEndpoint{},

		// Job endpoints
		&CreateJobEndpoint{},
		&ListJobsEndpoint{},
		&GetJobEndpoint{},
		&UpdateJobEndpoint{},
		&RetryJobEndpoint{},
		&DeleteJobEndpoint{},

		// Book endpoints
		&IngestEndpoint{},
		&UploadIngestEndpoint{},
		&ImportEPUBEndpoint{},
		&ListBooksEndpoint{},
		&GetBookEndpoint{},
		&GetBookChaptersEndpoint{},
		&RerunTocEndpoint{},
		&RepairOCREndpoint{},
		&RepairOCRTextEndpoint{},
		&RepairPDFTextEndpoint{},
		&RepairTocRangeEndpoint{},
		&RepairTocEntryEndpoint{},
		&ResolveTocEntryEndpoint{},
		&ExcludeTocEntryEndpoint{},
		&QuarantineOCREndpoint{},

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
		&ExtractedImageEndpoint{},
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
