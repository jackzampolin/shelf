package llmcall

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"regexp"
	"strings"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// validIDPattern matches valid IDs (UUIDs, DefraDB DocIDs, or simple alphanumeric).
var validIDPattern = regexp.MustCompile(`^[a-zA-Z0-9_-]+$`)

// validKeyPattern matches valid prompt keys (alphanumeric with dots, underscores, hyphens).
var validKeyPattern = regexp.MustCompile(`^[a-zA-Z0-9._-]+$`)

// validateID checks that an ID is safe for GraphQL interpolation.
func validateID(id string) error {
	if id == "" {
		return nil
	}
	if len(id) > 128 {
		return fmt.Errorf("id too long (max 128 chars)")
	}
	if !validIDPattern.MatchString(id) {
		return fmt.Errorf("invalid id format: must be alphanumeric with _ or -")
	}
	return nil
}

// validateKey checks that a key is safe for GraphQL interpolation.
func validateKey(key string) error {
	if key == "" {
		return nil
	}
	if len(key) > 128 {
		return fmt.Errorf("key too long (max 128 chars)")
	}
	if !validKeyPattern.MatchString(key) {
		return fmt.Errorf("invalid key format: must be alphanumeric with . _ or -")
	}
	return nil
}

// Store provides access to LLM call records in DefraDB.
type Store struct {
	client *defra.Client
}

// NewStore creates a new LLMCall store.
func NewStore(client *defra.Client) *Store {
	return &Store{client: client}
}

// QueryFilter specifies filters for listing LLM calls.
type QueryFilter struct {
	BookID    string
	PageID    string
	JobID     string
	PromptKey string
	Provider  string
	Model     string
	After     *time.Time
	Before    *time.Time
	Success   *bool
	Limit     int
	Offset    int
}

// Get retrieves a single LLM call by ID.
// Returns (nil, nil) if no call with the given ID exists.
func (s *Store) Get(ctx context.Context, id string) (*Call, error) {
	if err := validateID(id); err != nil {
		return nil, fmt.Errorf("invalid id: %w", err)
	}

	query := fmt.Sprintf(`{
		LLMCall(filter: {id: {_eq: %q}}) {
			id
			timestamp
			latency_ms
			book_id
			page_id
			job_id
			prompt_key
			prompt_cid
			provider
			model
			temperature
			input_tokens
			output_tokens
			response
			tool_calls
			success
			error
		}
	}`, id)

	resp, err := s.client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("graphql error: %s", errMsg)
	}

	calls, err := parseLLMCalls(resp.Data)
	if err != nil {
		return nil, err
	}
	if len(calls) == 0 {
		return nil, nil
	}
	return &calls[0], nil
}

// List retrieves LLM calls matching the filter.
func (s *Store) List(ctx context.Context, filter QueryFilter) ([]Call, error) {
	// Validate all filter inputs to prevent GraphQL injection
	for field, value := range map[string]string{
		"book_id":    filter.BookID,
		"page_id":    filter.PageID,
		"job_id":     filter.JobID,
		"prompt_key": filter.PromptKey,
		"provider":   filter.Provider,
		"model":      filter.Model,
	} {
		if field == "prompt_key" {
			if err := validateKey(value); err != nil {
				return nil, fmt.Errorf("invalid %s: %w", field, err)
			}
		} else {
			if err := validateID(value); err != nil {
				return nil, fmt.Errorf("invalid %s: %w", field, err)
			}
		}
	}

	// Build filter conditions
	var conditions []string

	if filter.BookID != "" {
		conditions = append(conditions, fmt.Sprintf(`book_id: {_eq: %q}`, filter.BookID))
	}
	if filter.PageID != "" {
		conditions = append(conditions, fmt.Sprintf(`page_id: {_eq: %q}`, filter.PageID))
	}
	if filter.JobID != "" {
		conditions = append(conditions, fmt.Sprintf(`job_id: {_eq: %q}`, filter.JobID))
	}
	if filter.PromptKey != "" {
		conditions = append(conditions, fmt.Sprintf(`prompt_key: {_eq: %q}`, filter.PromptKey))
	}
	if filter.Provider != "" {
		conditions = append(conditions, fmt.Sprintf(`provider: {_eq: %q}`, filter.Provider))
	}
	if filter.Model != "" {
		conditions = append(conditions, fmt.Sprintf(`model: {_eq: %q}`, filter.Model))
	}
	if filter.Success != nil {
		conditions = append(conditions, fmt.Sprintf(`success: {_eq: %t}`, *filter.Success))
	}
	if filter.After != nil {
		conditions = append(conditions, fmt.Sprintf(`timestamp: {_gt: %q}`, filter.After.Format(time.RFC3339)))
	}
	if filter.Before != nil {
		conditions = append(conditions, fmt.Sprintf(`timestamp: {_lt: %q}`, filter.Before.Format(time.RFC3339)))
	}

	// Build query
	filterStr := ""
	if len(conditions) > 0 {
		filterStr = fmt.Sprintf("filter: {%s}", strings.Join(conditions, ", "))
	}

	// Add limit/offset
	var args []string
	if filterStr != "" {
		args = append(args, filterStr)
	}
	if filter.Limit > 0 {
		args = append(args, fmt.Sprintf("limit: %d", filter.Limit))
	}
	if filter.Offset > 0 {
		args = append(args, fmt.Sprintf("offset: %d", filter.Offset))
	}

	argsStr := ""
	if len(args) > 0 {
		argsStr = fmt.Sprintf("(%s)", strings.Join(args, ", "))
	}

	query := fmt.Sprintf(`{
		LLMCall%s {
			id
			timestamp
			latency_ms
			book_id
			page_id
			job_id
			prompt_key
			prompt_cid
			provider
			model
			temperature
			input_tokens
			output_tokens
			response
			tool_calls
			success
			error
		}
	}`, argsStr)

	resp, err := s.client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("graphql error: %s", errMsg)
	}

	return parseLLMCalls(resp.Data)
}

// CountByPromptKey returns call counts grouped by prompt key.
// NOTE: This fetches all LLM calls for the book and aggregates client-side
// because DefraDB doesn't support GROUP BY. This is O(n) in memory where n is
// the number of LLM calls for the book. For books with many calls (10k+),
// consider caching results or implementing pagination.
func (s *Store) CountByPromptKey(ctx context.Context, bookID string) (map[string]int, error) {
	filter := QueryFilter{BookID: bookID}
	calls, err := s.List(ctx, filter)
	if err != nil {
		return nil, err
	}

	counts := make(map[string]int)
	for _, c := range calls {
		counts[c.PromptKey]++
	}
	return counts, nil
}

// parseLLMCalls parses LLMCall entries from GraphQL response data.
func parseLLMCalls(data map[string]any) ([]Call, error) {
	callData, ok := data["LLMCall"]
	if !ok {
		return nil, nil
	}

	docs, ok := callData.([]any)
	if !ok {
		return nil, fmt.Errorf("unexpected LLMCall type: %T", callData)
	}

	calls := make([]Call, 0, len(docs))
	for i, d := range docs {
		doc, ok := d.(map[string]any)
		if !ok {
			slog.Warn("skipping malformed LLM call document",
				"index", i,
				"type", fmt.Sprintf("%T", d))
			continue
		}

		call := Call{}
		if v, ok := doc["id"].(string); ok {
			call.ID = v
		}
		if v, ok := doc["timestamp"].(string); ok {
			if t, err := time.Parse(time.RFC3339, v); err != nil {
				slog.Debug("failed to parse LLM call timestamp",
					"id", call.ID,
					"raw_value", v,
					"error", err)
			} else {
				call.Timestamp = t
			}
		}
		if v, ok := doc["latency_ms"].(float64); ok {
			call.LatencyMs = int(v)
		}
		if v, ok := doc["book_id"].(string); ok {
			call.BookID = v
		}
		if v, ok := doc["page_id"].(string); ok {
			call.PageID = v
		}
		if v, ok := doc["job_id"].(string); ok {
			call.JobID = v
		}
		if v, ok := doc["prompt_key"].(string); ok {
			call.PromptKey = v
		}
		if v, ok := doc["prompt_cid"].(string); ok {
			call.PromptCID = v
		}
		if v, ok := doc["provider"].(string); ok {
			call.Provider = v
		}
		if v, ok := doc["model"].(string); ok {
			call.Model = v
		}
		if v, ok := doc["temperature"].(float64); ok {
			call.Temperature = &v
		}
		if v, ok := doc["input_tokens"].(float64); ok {
			call.InputTokens = int(v)
		}
		if v, ok := doc["output_tokens"].(float64); ok {
			call.OutputTokens = int(v)
		}
		if v, ok := doc["response"].(string); ok {
			call.Response = v
		}
		if v, ok := doc["success"].(bool); ok {
			call.Success = v
		}
		if v, ok := doc["error"].(string); ok {
			call.Error = v
		}

		// Handle tool_calls JSON
		if v := doc["tool_calls"]; v != nil {
			if data, err := json.Marshal(v); err != nil {
				slog.Warn("failed to serialize tool_calls from DB",
					"id", call.ID,
					"error", err)
			} else {
				call.ToolCalls = data
			}
		}

		calls = append(calls, call)
	}

	return calls, nil
}
