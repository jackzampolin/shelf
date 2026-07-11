package providers

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/google/uuid"
)

const endpointFailureCooldown = 90 * time.Second

// doRequest makes an HTTP request to OpenRouter with retry logic.
func (c *OpenAIChatClient) doRequest(ctx context.Context, path string, body any) (*openRouterResponse, error) {
	// Cast to openRouterRequest for nonce injection
	orReq, ok := body.(*openRouterRequest)
	if !ok {
		return nil, fmt.Errorf("body must be *openRouterRequest")
	}

	var lastErr error
	for attempt := 0; attempt < c.maxRetries; attempt++ {
		// Check context before each attempt
		if err := ctx.Err(); err != nil {
			return nil, err
		}

		// Inject nonce for retries on 413/422 (makes request "different")
		if attempt > 0 && lastErr != nil {
			c.injectNonce(orReq, attempt)
		}

		bodyBytes, err := json.Marshal(orReq)
		if err != nil {
			return nil, fmt.Errorf("failed to marshal request: %w", err)
		}

		baseURL, releaseEndpoint := c.acquireBaseURLForRequest()
		req, err := http.NewRequestWithContext(ctx, "POST", baseURL+path, bytes.NewReader(bodyBytes))
		if err != nil {
			releaseEndpoint()
			return nil, fmt.Errorf("failed to create request: %w", err)
		}

		req.Header.Set("Content-Type", "application/json")
		if c.apiKey != "" {
			req.Header.Set("Authorization", "Bearer "+c.apiKey)
		}
		if c.sendVendorHeaders {
			req.Header.Set("HTTP-Referer", "https://github.com/jackzampolin/shelf")
			req.Header.Set("X-Title", "Shelf")
		}

		resp, err := c.client.Do(req)
		if err != nil {
			releaseEndpoint()
			// Network error - retry
			c.markEndpointFailure(baseURL)
			lastErr = fmt.Errorf("request failed: %w", err)
			c.sleepWithJitter(ctx, attempt)
			continue
		}

		respBody, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		releaseEndpoint()
		if err != nil {
			lastErr = fmt.Errorf("failed to read response: %w", err)
			c.sleepWithJitter(ctx, attempt)
			continue
		}

		// Check if we should retry based on status code
		if c.shouldRetry(resp.StatusCode) {
			if c.shouldCooldownEndpoint(resp.StatusCode) {
				c.markEndpointFailure(baseURL)
			}
			lastErr = fmt.Errorf("OpenRouter error (status %d): %s", resp.StatusCode, string(respBody))
			c.sleepWithJitter(ctx, attempt)
			continue
		}

		// Non-retryable error
		if resp.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("OpenRouter error (status %d): %s", resp.StatusCode, string(respBody))
		}
		c.markEndpointSuccess(baseURL)

		var orResp openRouterResponse
		if err := json.Unmarshal(respBody, &orResp); err != nil {
			return nil, fmt.Errorf("failed to unmarshal response: %w", err)
		}

		// Check for retryable response-level issues (API returned 200 but with error or empty choices)
		if retryable, err := c.shouldRetryResponse(&orResp); retryable {
			lastErr = err
			c.sleepWithJitter(ctx, attempt)
			continue
		}

		return &orResp, nil
	}

	return nil, fmt.Errorf("max retries (%d) exceeded: %w", c.maxRetries, lastErr)
}

func (c *OpenAIChatClient) markEndpointFailure(baseURL string) {
	if c.endpoints == nil {
		return
	}
	c.endpoints.MarkFailure(baseURL, endpointFailureCooldown)
}

func (c *OpenAIChatClient) markEndpointSuccess(baseURL string) {
	if c.endpoints == nil {
		return
	}
	c.endpoints.MarkSuccess(baseURL)
}

func (c *OpenAIChatClient) shouldCooldownEndpoint(statusCode int) bool {
	return statusCode >= 500
}

// shouldRetry returns true for status codes that should be retried.
func (c *OpenAIChatClient) shouldRetry(statusCode int) bool {
	switch statusCode {
	case 413: // Payload Too Large - retry with nonce
		return true
	case 422: // Unprocessable Entity - retry with nonce (often cache/format issues)
		return true
	case 429: // Rate Limited
		return true
	case 520, 521, 522, 523, 524: // Cloudflare errors
		return true
	default:
		// Retry on server errors (500+)
		return statusCode >= 500
	}
}

// shouldRetryResponse checks if a 200 OK response has retryable content issues.
// Returns (true, error) if retryable, (false, nil) if not.
func (c *OpenAIChatClient) shouldRetryResponse(resp *openRouterResponse) (bool, error) {
	// API-level error in response body - some are retryable
	if resp.Error != nil {
		// Check for retryable error codes
		code := fmt.Sprintf("%v", resp.Error.Code)
		switch code {
		case "overloaded", "rate_limit_exceeded", "503", "502", "500":
			return true, fmt.Errorf("OpenRouter API error (retryable): %s", resp.Error.Message)
		}
		// Non-retryable API errors (content_filter, invalid_request, etc.)
		return false, nil
	}

	// Empty choices - likely transient, worth retrying
	if len(resp.Choices) == 0 {
		return true, fmt.Errorf("empty choices in response (model=%s, id=%s)", resp.Model, resp.ID)
	}

	return false, nil
}

// injectNonce adds a unique comment to the last user message to make the request different.
// This helps bypass caching issues that can cause 413/422 errors.
func (c *OpenAIChatClient) injectNonce(req *openRouterRequest, attempt int) {
	if len(req.Messages) == 0 {
		return
	}

	// Find the last user message
	for i := len(req.Messages) - 1; i >= 0; i-- {
		if req.Messages[i].Role == "user" {
			nonce := uuid.New().String()[:16]
			comment := fmt.Sprintf("\n<!-- retry_%d_id: %s -->", attempt, nonce)

			// Handle both string and array content
			switch content := req.Messages[i].Content.(type) {
			case string:
				req.Messages[i].Content = content + comment
			case []any:
				// For multipart content, find text part and append
				for j, part := range content {
					if partMap, ok := part.(map[string]any); ok {
						if partMap["type"] == "text" {
							if text, ok := partMap["text"].(string); ok {
								partMap["text"] = text + comment
								content[j] = partMap
								break
							}
						}
					}
				}
				req.Messages[i].Content = content
			}
			break
		}
	}
}

// sleepWithJitter sleeps for a duration with jitter, respecting context cancellation.
func (c *OpenAIChatClient) sleepWithJitter(ctx context.Context, attempt int) {
	// Base delay with exponential backoff: 0.5s, 1s, 2s, ...
	baseDelay := c.retryDelay * time.Duration(1<<attempt)
	if baseDelay > 10*time.Second {
		baseDelay = 10 * time.Second
	}

	// Add jitter: -20% to +30%
	jitter := time.Duration(float64(baseDelay) * (0.8 + 0.5*float64(time.Now().UnixNano()%1000)/1000))

	select {
	case <-ctx.Done():
	case <-time.After(jitter):
	}
}
