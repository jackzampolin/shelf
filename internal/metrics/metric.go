// Package metrics provides cost and usage tracking for LLM/OCR operations.
package metrics

import "time"

// Metric represents a single recorded metric for an LLM or OCR call.
// Metrics are append-only records stored in DefraDB with full attribution.
type Metric struct {
	ID string `json:"_docID,omitempty"`

	// Attribution (for filtering/aggregation)
	JobID   string `json:"job_id,omitempty"`
	BookID  string `json:"book_id,omitempty"`
	Stage   string `json:"stage,omitempty"`
	ItemKey string `json:"item_key,omitempty"` // e.g., "page_0001", "toc_entry_5"

	// Provider info
	Provider string `json:"provider,omitempty"`
	Model    string `json:"model,omitempty"`

	// Output reference (version-specific)
	OutputDocID string `json:"output_doc_id,omitempty"` // Stable doc reference
	OutputCID   string `json:"output_cid,omitempty"`    // Exact version (CID)
	OutputType  string `json:"output_type,omitempty"`   // Collection name

	// Cost and tokens
	CostUSD          float64 `json:"cost_usd,omitempty"`
	PromptTokens     int     `json:"prompt_tokens,omitempty"`
	CompletionTokens int     `json:"completion_tokens,omitempty"`
	ReasoningTokens  int     `json:"reasoning_tokens,omitempty"`
	TotalTokens      int     `json:"total_tokens,omitempty"`

	// Timing
	QueueSeconds     float64 `json:"queue_seconds,omitempty"`
	ExecutionSeconds float64 `json:"execution_seconds,omitempty"`
	TotalSeconds     float64 `json:"total_seconds,omitempty"`

	// Status
	Success   bool   `json:"success"`
	ErrorType string `json:"error_type,omitempty"`

	// Metadata
	CreatedAt time.Time `json:"created_at,omitempty"`
}

// ToMap converts the metric to a map for DefraDB storage.
func (m *Metric) ToMap() map[string]any {
	data := map[string]any{
		"success":    m.Success,
		"created_at": m.CreatedAt.Format(time.RFC3339),
	}

	// Attribution
	if m.JobID != "" {
		data["job_id"] = m.JobID
	}
	if m.BookID != "" {
		data["book_id"] = m.BookID
	}
	if m.Stage != "" {
		data["stage"] = m.Stage
	}
	if m.ItemKey != "" {
		data["item_key"] = m.ItemKey
	}

	// Provider
	if m.Provider != "" {
		data["provider"] = m.Provider
	}
	if m.Model != "" {
		data["model"] = m.Model
	}

	// Output reference
	if m.OutputDocID != "" {
		data["output_doc_id"] = m.OutputDocID
	}
	if m.OutputCID != "" {
		data["output_cid"] = m.OutputCID
	}
	if m.OutputType != "" {
		data["output_type"] = m.OutputType
	}

	// Cost and tokens
	if m.CostUSD > 0 {
		data["cost_usd"] = m.CostUSD
	}
	if m.PromptTokens > 0 {
		data["prompt_tokens"] = m.PromptTokens
	}
	if m.CompletionTokens > 0 {
		data["completion_tokens"] = m.CompletionTokens
	}
	if m.ReasoningTokens > 0 {
		data["reasoning_tokens"] = m.ReasoningTokens
	}
	if m.TotalTokens > 0 {
		data["total_tokens"] = m.TotalTokens
	}

	// Timing
	if m.QueueSeconds > 0 {
		data["queue_seconds"] = m.QueueSeconds
	}
	if m.ExecutionSeconds > 0 {
		data["execution_seconds"] = m.ExecutionSeconds
	}
	if m.TotalSeconds > 0 {
		data["total_seconds"] = m.TotalSeconds
	}

	// Error
	if m.ErrorType != "" {
		data["error_type"] = m.ErrorType
	}

	return data
}
