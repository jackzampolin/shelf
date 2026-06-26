package providers

import (
	"context"
	"fmt"
	"net/http"
	"time"
)

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

// OpenRouterClient implements LLMClient against an OpenAI-compatible chat API.
// It backs two presets: NewOpenRouterClient (the OpenRouter cloud API) and
// NewOpenAICompatClient (a self-hosted vLLM/OpenAI-compatible server). The
// OpenRouter-specific behaviors below are gated so the self-hosted preset owns
// its own identity, health, auth, and request shape.
// TODO(naming): rename this struct to a neutral openAIChatClient once the
// self-hosted providers settle; kept as-is here to minimize diff risk.
type OpenRouterClient struct {
	name         string // provider identity reported by Name() and on results
	apiKey       string
	baseURL      string
	endpoints    *EndpointPool // optional; round-robins request base URLs when set
	defaultModel string
	client       *http.Client

	// OpenRouter-specific behavior gates (true for the OpenRouter preset).
	sendUsageInclude  bool   // send the OpenRouter `usage:{include:true}` request flag
	sendVendorHeaders bool   // send OpenRouter HTTP-Referer / X-Title headers
	healthPath        string // path (relative to baseURL) for HealthCheck

	// Rate limiting
	rps        float64
	maxRetries int
	retryDelay time.Duration
}

// NewOpenRouterClient creates a new OpenRouter client.
func NewOpenRouterClient(cfg OpenRouterConfig) *OpenRouterClient {
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

	return &OpenRouterClient{
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
func (c *OpenRouterClient) Name() string {
	return c.name
}

// baseURLForRequest returns the base URL to use for the next request,
// round-robining across configured endpoints when present.
func (c *OpenRouterClient) baseURLForRequest() string {
	if c.endpoints != nil && c.endpoints.Len() > 0 {
		return c.endpoints.Next()
	}
	return c.baseURL
}

// RequestsPerSecond returns the RPS limit for rate limiting.
func (c *OpenRouterClient) RequestsPerSecond() float64 {
	return c.rps
}

// MaxConcurrency returns the max concurrent in-flight requests.
// Returns 0 to use DefaultMaxConcurrency.
func (c *OpenRouterClient) MaxConcurrency() int {
	return 0
}

// MaxRetries returns the maximum retry attempts.
func (c *OpenRouterClient) MaxRetries() int {
	return c.maxRetries
}

// RetryDelayBase returns the base delay between retries.
func (c *OpenRouterClient) RetryDelayBase() time.Duration {
	return c.retryDelay
}

// HealthCheck verifies the API is reachable and (when keyed) the API key is valid.
// OpenRouter uses /auth/key; the OpenAI-compatible preset uses /models.
func (c *OpenRouterClient) HealthCheck(ctx context.Context) error {
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
var _ LLMClient = (*OpenRouterClient)(nil)
