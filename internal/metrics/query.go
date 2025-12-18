package metrics

import (
	"context"
	"fmt"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// Query provides queries for metrics.
type Query struct {
	client *defra.Client
}

// NewQuery creates a new metrics query helper.
func NewQuery(client *defra.Client) *Query {
	return &Query{client: client}
}

// Filter specifies query filters.
type Filter struct {
	JobID       string
	BookID      string
	Stage       string
	Provider    string
	Model       string
	OutputDocID string
	OutputCID   string
	After       time.Time
	Before      time.Time
	Success     *bool // nil = any, true = success only, false = errors only
}

// buildFilterClause builds a GraphQL filter clause from a Filter.
func buildFilterClause(f Filter) string {
	parts := []string{}

	if f.JobID != "" {
		parts = append(parts, fmt.Sprintf(`job_id: {_eq: "%s"}`, f.JobID))
	}
	if f.BookID != "" {
		parts = append(parts, fmt.Sprintf(`book_id: {_eq: "%s"}`, f.BookID))
	}
	if f.Stage != "" {
		parts = append(parts, fmt.Sprintf(`stage: {_eq: "%s"}`, f.Stage))
	}
	if f.Provider != "" {
		parts = append(parts, fmt.Sprintf(`provider: {_eq: "%s"}`, f.Provider))
	}
	if f.Model != "" {
		parts = append(parts, fmt.Sprintf(`model: {_eq: "%s"}`, f.Model))
	}
	if f.OutputDocID != "" {
		parts = append(parts, fmt.Sprintf(`output_doc_id: {_eq: "%s"}`, f.OutputDocID))
	}
	if f.OutputCID != "" {
		parts = append(parts, fmt.Sprintf(`output_cid: {_eq: "%s"}`, f.OutputCID))
	}
	if !f.After.IsZero() {
		parts = append(parts, fmt.Sprintf(`created_at: {_gt: "%s"}`, f.After.Format(time.RFC3339)))
	}
	if !f.Before.IsZero() {
		parts = append(parts, fmt.Sprintf(`created_at: {_lt: "%s"}`, f.Before.Format(time.RFC3339)))
	}
	if f.Success != nil {
		parts = append(parts, fmt.Sprintf(`success: {_eq: %v}`, *f.Success))
	}

	if len(parts) == 0 {
		return ""
	}

	result := "filter: {"
	for i, p := range parts {
		if i > 0 {
			result += ", "
		}
		result += p
	}
	result += "}"
	return result
}

// List returns metrics matching the filter.
func (q *Query) List(ctx context.Context, f Filter, limit int) ([]Metric, error) {
	filterClause := buildFilterClause(f)

	query := `{
		Metric(%s) {
			_docID
			job_id
			book_id
			stage
			item_key
			provider
			model
			output_doc_id
			output_cid
			output_type
			cost_usd
			prompt_tokens
			completion_tokens
			reasoning_tokens
			total_tokens
			queue_seconds
			execution_seconds
			total_seconds
			success
			error_type
			created_at
		}
	}`

	if filterClause != "" {
		query = fmt.Sprintf(query, filterClause)
	} else {
		query = fmt.Sprintf(query, "")
	}

	resp, err := q.client.Execute(ctx, query, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query metrics: %w", err)
	}

	rawMetrics, ok := resp.Data["Metric"].([]any)
	if !ok {
		return nil, nil
	}

	var metrics []Metric
	for _, raw := range rawMetrics {
		if limit > 0 && len(metrics) >= limit {
			break
		}
		m, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		metrics = append(metrics, parseMetric(m))
	}

	return metrics, nil
}

// parseMetric converts a raw map to a Metric struct.
func parseMetric(m map[string]any) Metric {
	metric := Metric{}

	if v, ok := m["_docID"].(string); ok {
		metric.ID = v
	}
	if v, ok := m["job_id"].(string); ok {
		metric.JobID = v
	}
	if v, ok := m["book_id"].(string); ok {
		metric.BookID = v
	}
	if v, ok := m["stage"].(string); ok {
		metric.Stage = v
	}
	if v, ok := m["item_key"].(string); ok {
		metric.ItemKey = v
	}
	if v, ok := m["provider"].(string); ok {
		metric.Provider = v
	}
	if v, ok := m["model"].(string); ok {
		metric.Model = v
	}
	if v, ok := m["output_doc_id"].(string); ok {
		metric.OutputDocID = v
	}
	if v, ok := m["output_cid"].(string); ok {
		metric.OutputCID = v
	}
	if v, ok := m["output_type"].(string); ok {
		metric.OutputType = v
	}
	if v, ok := m["cost_usd"].(float64); ok {
		metric.CostUSD = v
	}
	if v, ok := m["prompt_tokens"].(float64); ok {
		metric.PromptTokens = int(v)
	}
	if v, ok := m["completion_tokens"].(float64); ok {
		metric.CompletionTokens = int(v)
	}
	if v, ok := m["reasoning_tokens"].(float64); ok {
		metric.ReasoningTokens = int(v)
	}
	if v, ok := m["total_tokens"].(float64); ok {
		metric.TotalTokens = int(v)
	}
	if v, ok := m["queue_seconds"].(float64); ok {
		metric.QueueSeconds = v
	}
	if v, ok := m["execution_seconds"].(float64); ok {
		metric.ExecutionSeconds = v
	}
	if v, ok := m["total_seconds"].(float64); ok {
		metric.TotalSeconds = v
	}
	if v, ok := m["success"].(bool); ok {
		metric.Success = v
	}
	if v, ok := m["error_type"].(string); ok {
		metric.ErrorType = v
	}
	if v, ok := m["created_at"].(string); ok {
		if t, err := time.Parse(time.RFC3339, v); err == nil {
			metric.CreatedAt = t
		}
	}

	return metric
}
