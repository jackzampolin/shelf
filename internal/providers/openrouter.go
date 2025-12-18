package providers

import (
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

// OpenRouterClient implements LLMClient using the OpenRouter API.
type OpenRouterClient struct {
	apiKey       string
	baseURL      string
	defaultModel string
	client       *http.Client
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
		cfg.Timeout = 120 * time.Second
	}
	if cfg.RPS == 0 {
		cfg.RPS = 150.0 // Default 150 RPS
	}
	if cfg.MaxRetries == 0 {
		cfg.MaxRetries = 3
	}
	if cfg.RetryDelay == 0 {
		cfg.RetryDelay = time.Second
	}

	return &OpenRouterClient{
		apiKey:       cfg.APIKey,
		baseURL:      cfg.BaseURL,
		defaultModel: cfg.DefaultModel,
		client: &http.Client{
			Timeout: cfg.Timeout,
		},
		rps:        cfg.RPS,
		maxRetries: cfg.MaxRetries,
		retryDelay: cfg.RetryDelay,
	}
}

// Name returns the client identifier.
func (c *OpenRouterClient) Name() string {
	return OpenRouterName
}

// RequestsPerSecond returns the RPS limit for rate limiting.
func (c *OpenRouterClient) RequestsPerSecond() float64 {
	return c.rps
}

// MaxRetries returns the maximum retry attempts.
func (c *OpenRouterClient) MaxRetries() int {
	return c.maxRetries
}

// RetryDelayBase returns the base delay between retries.
func (c *OpenRouterClient) RetryDelayBase() time.Duration {
	return c.retryDelay
}

// Verify interface
var _ LLMClient = (*OpenRouterClient)(nil)
