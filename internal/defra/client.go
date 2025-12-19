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

// CreateMany creates multiple documents in a collection in a single batch.
// Returns doc IDs in the same order as the input documents.
func (c *Client) CreateMany(ctx context.Context, collection string, inputs []map[string]any) ([]string, error) {
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

	query := fmt.Sprintf(`mutation { create_%s(input: %s) { _docID } }`, collection, inputArray)

	resp, err := c.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("create error: %s", errMsg)
	}

	// Extract _docIDs from response
	createKey := fmt.Sprintf("create_%s", collection)
	docs, ok := resp.Data[createKey].([]any)
	if !ok {
		return nil, fmt.Errorf("unexpected response format: %+v", resp.Data)
	}

	docIDs := make([]string, 0, len(docs))
	for _, d := range docs {
		if doc, ok := d.(map[string]any); ok {
			if docID, ok := doc["_docID"].(string); ok {
				docIDs = append(docIDs, docID)
			}
		}
	}

	if len(docIDs) != len(inputs) {
		return docIDs, fmt.Errorf("created %d docs but expected %d", len(docIDs), len(inputs))
	}

	return docIDs, nil
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

// mapToGraphQLInput converts a map to GraphQL input format.
func mapToGraphQLInput(input map[string]any) (string, error) {
	var parts []string
	for k, v := range input {
		var valStr string
		switch val := v.(type) {
		case string:
			valStr = fmt.Sprintf("%q", val)
		case int, int64, float64:
			valStr = fmt.Sprintf("%v", val)
		case bool:
			valStr = fmt.Sprintf("%v", val)
		default:
			b, err := json.Marshal(val)
			if err != nil {
				return "", fmt.Errorf("failed to marshal value for key %q: %w", k, err)
			}
			valStr = string(b)
		}
		parts = append(parts, fmt.Sprintf("%s: %s", k, valStr))
	}
	return "{" + strings.Join(parts, ", ") + "}", nil
}
