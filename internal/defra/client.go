package defra

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Sentinel errors for the defra package.
var (
	// ErrUnhealthy is returned when DefraDB health check fails.
	ErrUnhealthy = errors.New("defra health check failed")

	// ErrSinkClosed is returned when operations are attempted on a closed sink.
	ErrSinkClosed = errors.New("sink closed")
)

// Client is a DefraDB HTTP/GraphQL client.
type Client struct {
	url        string
	httpClient *http.Client
}

// NewClient creates a new DefraDB client.
func NewClient(url string) *Client {
	return &Client{
		url: strings.TrimSuffix(url, "/"),
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// GQLRequest represents a GraphQL request.
type GQLRequest struct {
	Query         string         `json:"query"`
	OperationName string         `json:"operationName,omitempty"`
	Variables     map[string]any `json:"variables,omitempty"`
}

// GQLResponse represents a GraphQL response.
type GQLResponse struct {
	Data   map[string]any `json:"data,omitempty"`
	Errors []GQLError     `json:"errors,omitempty"`
}

// GQLError represents a GraphQL error.
type GQLError struct {
	Message string `json:"message"`
	Path    []any  `json:"path,omitempty"`
}

// Error returns the first error message or empty string.
func (r *GQLResponse) Error() string {
	if len(r.Errors) == 0 {
		return ""
	}
	return r.Errors[0].Message
}

// HealthCheck checks if DefraDB is healthy.
func (c *Client) HealthCheck(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, "GET", c.url+"/health-check", nil)
	if err != nil {
		return err
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("unhealthy: status %d", resp.StatusCode)
	}
	return nil
}

// Execute sends a GraphQL request and returns the response.
func (c *Client) Execute(ctx context.Context, query string, variables map[string]any) (*GQLResponse, error) {
	reqBody := GQLRequest{
		Query:     query,
		Variables: variables,
	}

	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", c.url+"/api/v0/graphql", bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	var gqlResp GQLResponse
	if err := json.Unmarshal(respBody, &gqlResp); err != nil {
		return nil, fmt.Errorf("failed to unmarshal response: %w (body: %s)", err, string(respBody))
	}

	return &gqlResp, nil
}

// AddSchema adds a GraphQL schema to DefraDB.
func (c *Client) AddSchema(ctx context.Context, schema string) error {
	req, err := http.NewRequestWithContext(ctx, "POST", c.url+"/api/v0/schema", strings.NewReader(schema))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "text/plain")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("schema error (status %d): %s", resp.StatusCode, string(body))
	}
	return nil
}

// Query executes a query and returns the results.
func (c *Client) Query(ctx context.Context, query string) (*GQLResponse, error) {
	return c.Execute(ctx, query, nil)
}

// Mutation executes a mutation.
func (c *Client) Mutation(ctx context.Context, mutation string, variables map[string]any) (*GQLResponse, error) {
	return c.Execute(ctx, mutation, variables)
}

// Create creates a document in a collection.
func (c *Client) Create(ctx context.Context, collection string, input map[string]any) (string, error) {
	inputGQL, err := mapToGraphQLInput(input)
	if err != nil {
		return "", fmt.Errorf("failed to build input: %w", err)
	}
	query := fmt.Sprintf(`mutation { create_%s(input: %s) { _docID } }`, collection, inputGQL)

	resp, err := c.Execute(ctx, query, nil)
	if err != nil {
		return "", err
	}
	if errMsg := resp.Error(); errMsg != "" {
		return "", fmt.Errorf("create error: %s", errMsg)
	}

	// Extract _docID from response
	createKey := fmt.Sprintf("create_%s", collection)
	if docs, ok := resp.Data[createKey].([]any); ok && len(docs) > 0 {
		if doc, ok := docs[0].(map[string]any); ok {
			if docID, ok := doc["_docID"].(string); ok {
				return docID, nil
			}
		}
	}

	return "", fmt.Errorf("unexpected response format: %+v", resp.Data)
}

// CreateManyResult contains the result of a batch create operation.
type CreateManyResult struct {
	DocID  string
	Fields map[string]any
}

// CreateMany creates multiple documents in a collection in a single batch.
// The returnFields parameter specifies which fields to include in results for matching.
// If returnFields is empty, only _docID is returned.
// IMPORTANT: DefraDB may not return results in the same order as inputs.
// Use returnFields to include identifying fields (like page_num) for proper matching.
func (c *Client) CreateMany(ctx context.Context, collection string, inputs []map[string]any, returnFields ...string) ([]CreateManyResult, error) {
	if len(inputs) == 0 {
		return nil, nil
	}

	// Build array of GraphQL inputs: [{field: val}, {field: val}]
	var inputParts []string
	for _, input := range inputs {
		inputGQL, err := mapToGraphQLInput(input)
		if err != nil {
			return nil, fmt.Errorf("failed to build input: %w", err)
		}
		inputParts = append(inputParts, inputGQL)
	}
	inputArray := "[" + strings.Join(inputParts, ", ") + "]"

	// Build return fields: always include _docID, plus any requested fields
	fields := "_docID"
	for _, f := range returnFields {
		fields += " " + f
	}

	query := fmt.Sprintf(`mutation { create_%s(input: %s) { %s } }`, collection, inputArray, fields)

	resp, err := c.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("create error: %s", errMsg)
	}

	// Extract results from response
	createKey := fmt.Sprintf("create_%s", collection)
	docs, ok := resp.Data[createKey].([]any)
	if !ok {
		return nil, fmt.Errorf("unexpected response format: %+v", resp.Data)
	}

	results := make([]CreateManyResult, 0, len(docs))
	for _, d := range docs {
		if doc, ok := d.(map[string]any); ok {
			result := CreateManyResult{
				Fields: make(map[string]any),
			}
			if docID, ok := doc["_docID"].(string); ok {
				result.DocID = docID
			}
			// Copy all returned fields except _docID
			for k, v := range doc {
				if k != "_docID" {
					result.Fields[k] = v
				}
			}
			results = append(results, result)
		}
	}

	if len(results) != len(inputs) {
		return results, fmt.Errorf("created %d docs but expected %d", len(results), len(inputs))
	}

	return results, nil
}

// Update updates a document in a collection.
func (c *Client) Update(ctx context.Context, collection string, docID string, input map[string]any) error {
	inputGQL, err := mapToGraphQLInput(input)
	if err != nil {
		return fmt.Errorf("failed to build input: %w", err)
	}
	query := fmt.Sprintf(`mutation { update_%s(docID: %q, input: %s) { _docID } }`, collection, docID, inputGQL)

	resp, err := c.Execute(ctx, query, nil)
	if err != nil {
		return err
	}
	if errMsg := resp.Error(); errMsg != "" {
		return fmt.Errorf("update error: %s", errMsg)
	}
	return nil
}

// Delete deletes a document from a collection.
func (c *Client) Delete(ctx context.Context, collection string, docID string) error {
	query := fmt.Sprintf(`mutation { delete_%s(docID: %q) { _docID } }`, collection, docID)

	resp, err := c.Execute(ctx, query, nil)
	if err != nil {
		return err
	}
	if errMsg := resp.Error(); errMsg != "" {
		return fmt.Errorf("delete error: %s", errMsg)
	}
	return nil
}

// Upsert creates or updates a document based on a filter.
// If the filter matches exactly one document, it updates with updateInput.
// If no match, it creates with createInput.
// The filter must match 0 or 1 documents (errors if multiple matches).
func (c *Client) Upsert(ctx context.Context, collection string, filter, createInput, updateInput map[string]any) (string, error) {
	filterGQL, err := mapToGraphQLInput(filter)
	if err != nil {
		return "", fmt.Errorf("failed to build filter: %w", err)
	}
	createGQL, err := mapToGraphQLInput(createInput)
	if err != nil {
		return "", fmt.Errorf("failed to build create input: %w", err)
	}
	updateGQL, err := mapToGraphQLInput(updateInput)
	if err != nil {
		return "", fmt.Errorf("failed to build update input: %w", err)
	}

	query := fmt.Sprintf(`mutation { upsert_%s(filter: %s, create: %s, update: %s) { _docID } }`,
		collection, filterGQL, createGQL, updateGQL)

	resp, err := c.Execute(ctx, query, nil)
	if err != nil {
		return "", err
	}
	if errMsg := resp.Error(); errMsg != "" {
		return "", fmt.Errorf("upsert error: %s", errMsg)
	}

	// Extract _docID from response
	upsertKey := fmt.Sprintf("upsert_%s", collection)
	if docs, ok := resp.Data[upsertKey].([]any); ok && len(docs) > 0 {
		if doc, ok := docs[0].(map[string]any); ok {
			if docID, ok := doc["_docID"].(string); ok {
				return docID, nil
			}
		}
	}

	return "", fmt.Errorf("unexpected response format: %+v", resp.Data)
}

// mapToGraphQLInput converts a map to GraphQL input format.
func mapToGraphQLInput(input map[string]any) (string, error) {
	var parts []string
	for k, v := range input {
		valStr, err := valueToGraphQL(v)
		if err != nil {
			return "", fmt.Errorf("failed to convert value for key %q: %w", k, err)
		}
		parts = append(parts, fmt.Sprintf("%s: %s", k, valStr))
	}
	return "{" + strings.Join(parts, ", ") + "}", nil
}

// valueToGraphQL converts a Go value to GraphQL syntax.
func valueToGraphQL(v any) (string, error) {
	switch val := v.(type) {
	case string:
		return fmt.Sprintf("%q", val), nil
	case int:
		return fmt.Sprintf("%d", val), nil
	case int64:
		return fmt.Sprintf("%d", val), nil
	case float64:
		return fmt.Sprintf("%v", val), nil
	case bool:
		return fmt.Sprintf("%v", val), nil
	case map[string]any:
		// Recursively convert nested maps
		return mapToGraphQLInput(val)
	case []any:
		// Handle arrays
		var items []string
		for _, item := range val {
			itemStr, err := valueToGraphQL(item)
			if err != nil {
				return "", err
			}
			items = append(items, itemStr)
		}
		return "[" + strings.Join(items, ", ") + "]", nil
	default:
		// Fallback to JSON for complex types
		b, err := json.Marshal(val)
		if err != nil {
			return "", fmt.Errorf("failed to marshal value: %w", err)
		}
		return string(b), nil
	}
}
