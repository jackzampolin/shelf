package metrics

import (
	"context"
	"fmt"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
)

// Recorder handles recording metrics to DefraDB.
type Recorder struct {
	client *defra.Client
}

// NewRecorder creates a new metrics recorder.
func NewRecorder(client *defra.Client) *Recorder {
	return &Recorder{client: client}
}

// RecordOpts provides context for a metric recording.
type RecordOpts struct {
	JobID       string
	BookID      string
	Stage       string
	ItemKey     string // e.g., "page_0001"
	OutputDocID string // Stable doc reference
	OutputCID   string // Version-specific (from doc.Head().String())
	OutputType  string // Collection name (e.g., "Page", "OcrResult")
}

// Record stores a single metric in DefraDB.
func (r *Recorder) Record(ctx context.Context, m Metric) (string, error) {
	if m.CreatedAt.IsZero() {
		m.CreatedAt = time.Now()
	}
	return r.client.Create(ctx, "Metric", m.toMap())
}

// RecordLLMCall records metrics from an LLM chat result.
func (r *Recorder) RecordLLMCall(ctx context.Context, opts RecordOpts, result *providers.ChatResult) (string, error) {
	if result == nil {
		return "", fmt.Errorf("nil chat result")
	}

	m := Metric{
		// Attribution
		JobID:   opts.JobID,
		BookID:  opts.BookID,
		Stage:   opts.Stage,
		ItemKey: opts.ItemKey,

		// Output reference
		OutputDocID: opts.OutputDocID,
		OutputCID:   opts.OutputCID,
		OutputType:  opts.OutputType,

		// Provider info
		Provider: result.Provider,
		Model:    result.ModelUsed,

		// Cost and tokens
		CostUSD:          result.CostUSD,
		PromptTokens:     result.PromptTokens,
		CompletionTokens: result.CompletionTokens,
		ReasoningTokens:  result.ReasoningTokens,
		TotalTokens:      result.TotalTokens,

		// Timing
		QueueSeconds:     result.QueueTime.Seconds(),
		ExecutionSeconds: result.ExecutionTime.Seconds(),
		TotalSeconds:     result.TotalTime.Seconds(),

		// Status
		Success:   result.Success,
		ErrorType: result.ErrorType,

		// Metadata
		CreatedAt: time.Now(),
	}

	return r.Record(ctx, m)
}

// RecordOCRCall records metrics from an OCR result.
func (r *Recorder) RecordOCRCall(ctx context.Context, opts RecordOpts, provider string, result *providers.OCRResult) (string, error) {
	if result == nil {
		return "", fmt.Errorf("nil OCR result")
	}

	m := Metric{
		// Attribution
		JobID:   opts.JobID,
		BookID:  opts.BookID,
		Stage:   opts.Stage,
		ItemKey: opts.ItemKey,

		// Output reference
		OutputDocID: opts.OutputDocID,
		OutputCID:   opts.OutputCID,
		OutputType:  opts.OutputType,

		// Provider info
		Provider: provider,

		// Cost and timing
		CostUSD:          result.CostUSD,
		ExecutionSeconds: result.ExecutionTime.Seconds(),
		TotalSeconds:     result.ExecutionTime.Seconds(),

		// Status
		Success: result.Success,

		// Metadata
		CreatedAt: time.Now(),
	}

	if result.ErrorMessage != "" {
		m.ErrorType = "ocr_error"
	}

	return r.Record(ctx, m)
}

// RecordError records a failed operation as a metric.
func (r *Recorder) RecordError(ctx context.Context, opts RecordOpts, provider, model, errorType string, duration time.Duration) (string, error) {
	m := Metric{
		// Attribution
		JobID:   opts.JobID,
		BookID:  opts.BookID,
		Stage:   opts.Stage,
		ItemKey: opts.ItemKey,

		// Provider info
		Provider: provider,
		Model:    model,

		// Timing
		TotalSeconds: duration.Seconds(),

		// Status
		Success:   false,
		ErrorType: errorType,

		// Metadata
		CreatedAt: time.Now(),
	}

	return r.Record(ctx, m)
}
