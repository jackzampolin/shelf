package providers

import (
	"context"
	"fmt"
	"net/http"
	"sync"
	"time"
)

const exclusiveEndpointMinOutputTokens = 32768

const (
	OpenRouterName    = "openrouter"
	OpenRouterBaseURL = "https://openrouter.ai/api/v1"
)

// OpenRouterConfig holds configuration for the OpenRouter client.
type OpenRouterConfig struct {
	APIKey       string
	BaseURL      string
	DefaultModel string
	Timeout      time.Duration
	// Rate limiting
	RPS        float64       // Requests per second (default: 150)
	MaxRetries int           // Max retry attempts (default: 3)
	RetryDelay time.Duration // Base delay between retries (default: 1s)
}

// OpenAIChatClient implements LLMClient against an OpenAI-compatible chat API.
// It backs two presets: NewOpenRouterClient (the OpenRouter cloud API) and
// NewOpenAICompatClient (a self-hosted vLLM/OpenAI-compatible server). The
// OpenRouter-specific behaviors below are gated so the self-hosted preset owns
// its own identity, health, auth, and request shape.
type OpenAIChatClient struct {
	name         string // provider identity reported by Name() and on results
	apiKey       string
	baseURL      string
	endpoints    *EndpointPool // optional; load-balances request base URLs when set
	defaultModel string
	client       *http.Client

	// OpenRouter-specific behavior gates (true for the OpenRouter preset).
	sendUsageInclude  bool   // send the OpenRouter `usage:{include:true}` request flag
	sendVendorHeaders bool   // send OpenRouter HTTP-Referer / X-Title headers
	healthPath        string // path (relative to baseURL) for HealthCheck
	maxConcurrency    int    // max concurrent in-flight requests (0 = DefaultMaxConcurrency)

	// Rate limiting
	rps        float64
	maxRetries int
	retryDelay time.Duration
}

// NewOpenRouterClient creates a new OpenRouter client.
func NewOpenRouterClient(cfg OpenRouterConfig) *OpenAIChatClient {
	if cfg.BaseURL == "" {
		cfg.BaseURL = OpenRouterBaseURL
	}
	if cfg.DefaultModel == "" {
		cfg.DefaultModel = "anthropic/claude-3.5-sonnet"
	}
	if cfg.Timeout == 0 {
		cfg.Timeout = 500 * time.Second
	}
	if cfg.RPS == 0 {
		cfg.RPS = 150.0 // Default 150 RPS
	}
	if cfg.MaxRetries == 0 {
		cfg.MaxRetries = 7
	}
	if cfg.RetryDelay == 0 {
		cfg.RetryDelay = 2 * time.Second
	}

	return &OpenAIChatClient{
		name:         OpenRouterName,
		apiKey:       cfg.APIKey,
		baseURL:      cfg.BaseURL,
		defaultModel: cfg.DefaultModel,
		client: &http.Client{
			Timeout: cfg.Timeout,
		},
		sendUsageInclude:  true,
		sendVendorHeaders: true,
		healthPath:        "/auth/key",
		rps:               cfg.RPS,
		maxRetries:        cfg.MaxRetries,
		retryDelay:        cfg.RetryDelay,
	}
}

// Name returns the client identifier.
func (c *OpenAIChatClient) Name() string {
	return c.name
}

// baseURLForRequest returns the base URL to use for the next request,
// round-robining across configured endpoints when present.
func (c *OpenAIChatClient) baseURLForRequest() string {
	if c.endpoints != nil && c.endpoints.Len() > 0 {
		return c.endpoints.Next()
	}
	return c.baseURL
}

// acquireBaseURLForRequest reserves an endpoint for the duration of one HTTP
// attempt. The returned release function must be called after its response body
// is consumed.
func (c *OpenAIChatClient) acquireBaseURLForRequest(maxTokens int) (string, func()) {
	if c.endpoints != nil && c.endpoints.Len() > 0 {
		exclusive := maxTokens >= exclusiveEndpointMinOutputTokens
		var baseURL string
		if exclusive {
			baseURL = c.endpoints.AcquireExclusive()
		} else {
			baseURL = c.endpoints.Acquire()
		}
		var once sync.Once
		return baseURL, func() {
			once.Do(func() {
				if exclusive {
					c.endpoints.ReleaseExclusive(baseURL)
					return
				}
				c.endpoints.Release(baseURL)
			})
		}
	}
	return c.baseURL, func() {}
}

// RequestsPerSecond returns the RPS limit for rate limiting.
func (c *OpenAIChatClient) RequestsPerSecond() float64 {
	return c.rps
}

// MaxConcurrency returns the max concurrent in-flight requests.
// Returns 0 to use DefaultMaxConcurrency (the OpenRouter preset leaves it unset).
func (c *OpenAIChatClient) MaxConcurrency() int {
	return c.maxConcurrency
}

// EndpointStatuses reports live per-URL reservations for self-hosted clients.
func (c *OpenAIChatClient) EndpointStatuses() []EndpointStatus {
	if c.endpoints == nil {
		return nil
	}
	return c.endpoints.Status()
}

// MaxRetries returns the maximum retry attempts.
func (c *OpenAIChatClient) MaxRetries() int {
	return c.maxRetries
}

// ManagesRetries reports that doRequest consumes the configured retry budget.
func (c *OpenAIChatClient) ManagesRetries() bool { return true }

// RetryDelayBase returns the base delay between retries.
func (c *OpenAIChatClient) RetryDelayBase() time.Duration {
	return c.retryDelay
}

// HealthCheck verifies the API is reachable and (when keyed) the API key is valid.
// OpenRouter uses /auth/key; the OpenAI-compatible preset uses /models.
func (c *OpenAIChatClient) HealthCheck(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, "GET", c.baseURLForRequest()+c.healthPath, nil)
	if err != nil {
		return fmt.Errorf("failed to create health check request: %w", err)
	}

	// Only send auth when a key is configured (self-hosted servers may be keyless).
	if c.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
	}

	resp, err := c.client.Do(req)
	if err != nil {
		return fmt.Errorf("health check request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusUnauthorized {
		return fmt.Errorf("invalid API key")
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("health check failed with status %d", resp.StatusCode)
	}

	return nil
}

// Verify interface
var _ LLMClient = (*OpenAIChatClient)(nil)
