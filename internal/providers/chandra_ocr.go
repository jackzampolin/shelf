package providers

import (
	"context"
	"fmt"
	"time"
)

const (
	ChandraOCRName  = "chandra"
	ChandraOCRModel = "datalab-to/chandra-ocr-2"

	// DefaultChandraOCRPrompt instructs the Chandra vision model to transcribe a
	// page image to clean Markdown. Tunable once validated against a live server.
	DefaultChandraOCRPrompt = "Transcribe this document page image to clean, well-structured Markdown. " +
		"Preserve headings, lists, tables, and natural reading order. " +
		"Output only the Markdown content, with no commentary or code fences."

	defaultChandraRPS            = 50.0
	defaultChandraMaxConcurrency = 16
	defaultChandraMaxRetries     = 5
)

// ChandraOCRConfig configures the Chandra OCR provider, a vision model served
// over an OpenAI-compatible chat API (e.g. `vllm serve datalab-to/chandra-ocr-2`).
type ChandraOCRConfig struct {
	Name           string   // provider identity (default "chandra")
	BaseURLs       []string // self-hosted endpoints, round-robined
	APIKey         string   // optional; sent only when non-empty
	Model          string   // default datalab-to/chandra-ocr-2
	Prompt         string   // OCR instruction; default DefaultChandraOCRPrompt
	RateLimit      float64
	MaxConcurrency int
	MaxRetries     int
	RetryDelay     time.Duration
	Timeout        time.Duration
}

// ChandraOCRClient implements OCRProvider by sending each page image plus an OCR
// prompt to a Chandra vision model and returning the Markdown transcription.
// It wraps an OpenAI-compatible chat client, reusing its transport, round-robin,
// and retry machinery.
type ChandraOCRClient struct {
	name           string
	model          string
	prompt         string
	llm            *OpenRouterClient
	rateLimit      float64
	maxConcurrency int
	maxRetries     int
	retryDelay     time.Duration
}

// NewChandraOCRClient creates a Chandra OCR provider.
func NewChandraOCRClient(cfg ChandraOCRConfig) *ChandraOCRClient {
	name := cfg.Name
	if name == "" {
		name = ChandraOCRName
	}
	if cfg.Model == "" {
		cfg.Model = ChandraOCRModel
	}
	if cfg.Prompt == "" {
		cfg.Prompt = DefaultChandraOCRPrompt
	}
	if cfg.RateLimit == 0 {
		cfg.RateLimit = defaultChandraRPS
	}
	if cfg.MaxConcurrency == 0 {
		cfg.MaxConcurrency = defaultChandraMaxConcurrency
	}
	if cfg.MaxRetries == 0 {
		cfg.MaxRetries = defaultChandraMaxRetries
	}
	if cfg.RetryDelay == 0 {
		cfg.RetryDelay = 2 * time.Second
	}

	llm := NewOpenAICompatClient(OpenAICompatConfig{
		Name:         name,
		BaseURLs:     cfg.BaseURLs,
		APIKey:       cfg.APIKey,
		DefaultModel: cfg.Model,
		RPS:          cfg.RateLimit,
		MaxRetries:   cfg.MaxRetries,
		RetryDelay:   cfg.RetryDelay,
		Timeout:      cfg.Timeout,
	})

	return &ChandraOCRClient{
		name:           name,
		model:          cfg.Model,
		prompt:         cfg.Prompt,
		llm:            llm,
		rateLimit:      cfg.RateLimit,
		maxConcurrency: cfg.MaxConcurrency,
		maxRetries:     cfg.MaxRetries,
		retryDelay:     cfg.RetryDelay,
	}
}

// Name returns the provider identifier.
func (c *ChandraOCRClient) Name() string { return c.name }

// RequestsPerSecond returns the RPS limit for rate limiting.
func (c *ChandraOCRClient) RequestsPerSecond() float64 { return c.rateLimit }

// MaxConcurrency returns the max concurrent in-flight OCR requests.
func (c *ChandraOCRClient) MaxConcurrency() int { return c.maxConcurrency }

// MaxRetries returns the maximum retry attempts.
func (c *ChandraOCRClient) MaxRetries() int { return c.maxRetries }

// RetryDelayBase returns the base delay between retries.
func (c *ChandraOCRClient) RetryDelayBase() time.Duration { return c.retryDelay }

// HealthCheck verifies the underlying chat server is reachable.
func (c *ChandraOCRClient) HealthCheck(ctx context.Context) error {
	return c.llm.HealthCheck(ctx)
}

// ProcessImage transcribes a single page image to Markdown via the Chandra model.
func (c *ChandraOCRClient) ProcessImage(ctx context.Context, image []byte, pageNum int) (*OCRResult, error) {
	start := time.Now()

	res, err := c.llm.Chat(ctx, &ChatRequest{
		Model: c.model,
		Messages: []Message{{
			Role:    "user",
			Content: c.prompt,
			Images:  [][]byte{image},
		}},
	})
	if err != nil {
		return &OCRResult{
			Success:       false,
			ExecutionTime: time.Since(start),
			ErrorMessage:  err.Error(),
		}, err
	}
	if !res.Success {
		return &OCRResult{
			Success:       false,
			ExecutionTime: time.Since(start),
			ErrorMessage:  res.ErrorMessage,
		}, fmt.Errorf("chandra OCR failed (page %d): %s", pageNum, res.ErrorMessage)
	}

	return &OCRResult{
		Success:       true,
		Text:          res.Content,
		CostUSD:       0, // local inference; see ADR 011
		ExecutionTime: time.Since(start),
		Metadata: map[string]any{
			"model":             res.ModelUsed,
			"prompt_tokens":     res.PromptTokens,
			"completion_tokens": res.CompletionTokens,
		},
	}, nil
}

var _ OCRProvider = (*ChandraOCRClient)(nil)
