package providers

import (
	"net/http"
	"time"
)

// OpenAICompatName is the default provider identity for self-hosted,
// OpenAI-compatible chat servers (e.g. vLLM serving Qwen on the DGX Sparks).
const OpenAICompatName = "openai-compat"

// OpenAICompatConfig configures a client for a self-hosted OpenAI-compatible
// chat API. Unlike OpenRouter, it round-robins across BaseURLs, sends no vendor
// headers or `usage.include` flag, sends auth only when APIKey is set, and
// reports zero cost (the server returns no cost fields).
type OpenAICompatConfig struct {
	Name         string   // provider identity (default "openai-compat")
	BaseURLs     []string // self-hosted endpoints, round-robined; first is the fallback base
	APIKey       string   // optional; sent as Bearer only when non-empty
	DefaultModel string
	Timeout      time.Duration
	RPS          float64
	MaxRetries   int
	RetryDelay   time.Duration
}

// NewOpenAICompatClient creates an LLMClient for a self-hosted OpenAI-compatible
// server. It reuses the OpenRouter client's chat/transport/structured-output
// machinery (vLLM speaks the same wire format) but owns its own identity,
// health endpoint (/models), auth, and request shape.
func NewOpenAICompatClient(cfg OpenAICompatConfig) *OpenRouterClient {
	name := cfg.Name
	if name == "" {
		name = OpenAICompatName
	}
	if cfg.Timeout == 0 {
		cfg.Timeout = 500 * time.Second
	}
	if cfg.RPS == 0 {
		cfg.RPS = 150.0
	}
	if cfg.MaxRetries == 0 {
		cfg.MaxRetries = 7
	}
	if cfg.RetryDelay == 0 {
		cfg.RetryDelay = 2 * time.Second
	}

	baseURL := ""
	if len(cfg.BaseURLs) > 0 {
		baseURL = cfg.BaseURLs[0]
	}

	return &OpenRouterClient{
		name:         name,
		apiKey:       cfg.APIKey,
		baseURL:      baseURL,
		endpoints:    NewEndpointPool(cfg.BaseURLs),
		defaultModel: cfg.DefaultModel,
		client: &http.Client{
			Timeout: cfg.Timeout,
		},
		sendUsageInclude:  false,
		sendVendorHeaders: false,
		healthPath:        "/models",
		rps:               cfg.RPS,
		maxRetries:        cfg.MaxRetries,
		retryDelay:        cfg.RetryDelay,
	}
}
