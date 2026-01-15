package providers

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const (
	DeepInfraTTSName              = "deepinfra-tts"
	DeepInfraTTSDefaultModel      = "ResembleAI/chatterbox-turbo"
	DeepInfraTTSInferenceEndpoint = "https://api.deepinfra.com/v1/inference"
)

// DeepInfraTTSConfig holds configuration for the DeepInfra TTS client.
type DeepInfraTTSConfig struct {
	APIKey      string
	Model       string        // e.g., "ResembleAI/chatterbox-turbo" or "ResembleAI/chatterbox"
	Voice       string        // Voice ID (optional - uses default if empty)
	Format      string        // Output format: mp3, wav, opus, flac (default: mp3)
	Temperature float64       // Generation temperature (0-2, default: 0.8)
	Exaggeration float64      // Emotion exaggeration factor (0-1, default: 0.5)
	CFG         float64       // Classifier-free guidance (0-1, default: 0.5)
	Timeout     time.Duration
	RateLimit   float64       // Requests per second
	MaxRetries  int           // Max retry attempts (default: 5)
	RetryDelay  time.Duration // Base delay between retries (default: 2s)
}

// DeepInfraTTSClient implements TTSProvider using DeepInfra's Chatterbox model.
type DeepInfraTTSClient struct {
	apiKey       string
	model        string
	voice        string
	format       string
	temperature  float64
	exaggeration float64
	cfg          float64
	rateLimit    float64
	maxRetries   int
	retryDelay   time.Duration
	client       *http.Client
}

// NewDeepInfraTTSClient creates a new DeepInfra TTS client.
func NewDeepInfraTTSClient(cfg DeepInfraTTSConfig) *DeepInfraTTSClient {
	if cfg.Model == "" {
		cfg.Model = DeepInfraTTSDefaultModel
	}
	if cfg.Format == "" {
		cfg.Format = "mp3"
	}
	if cfg.Temperature == 0 {
		cfg.Temperature = 0.8
	}
	if cfg.Exaggeration == 0 {
		cfg.Exaggeration = 0.5
	}
	if cfg.CFG == 0 {
		cfg.CFG = 0.5
	}
	if cfg.Timeout == 0 {
		cfg.Timeout = 300 * time.Second // TTS can be slow for long text (5 minutes)
	}
	if cfg.RateLimit == 0 {
		cfg.RateLimit = 5.0 // Conservative default
	}
	if cfg.MaxRetries == 0 {
		cfg.MaxRetries = 5
	}
	if cfg.RetryDelay == 0 {
		cfg.RetryDelay = 2 * time.Second
	}

	return &DeepInfraTTSClient{
		apiKey:       cfg.APIKey,
		model:        cfg.Model,
		voice:        cfg.Voice,
		format:       cfg.Format,
		temperature:  cfg.Temperature,
		exaggeration: cfg.Exaggeration,
		cfg:          cfg.CFG,
		rateLimit:    cfg.RateLimit,
		maxRetries:   cfg.MaxRetries,
		retryDelay:   cfg.RetryDelay,
		client: &http.Client{
			Timeout: cfg.Timeout,
		},
	}
}

// Name returns the provider identifier.
func (c *DeepInfraTTSClient) Name() string {
	return DeepInfraTTSName
}

// RequestsPerSecond returns the rate limit.
func (c *DeepInfraTTSClient) RequestsPerSecond() float64 {
	return c.rateLimit
}

// MaxConcurrency returns the max concurrent in-flight requests.
// TTS requests can be slow, so limit concurrency to avoid overwhelming the API.
func (c *DeepInfraTTSClient) MaxConcurrency() int {
	return 10
}

// MaxRetries returns the maximum retry attempts.
func (c *DeepInfraTTSClient) MaxRetries() int {
	return c.maxRetries
}

// RetryDelayBase returns the base delay for exponential backoff.
func (c *DeepInfraTTSClient) RetryDelayBase() time.Duration {
	return c.retryDelay
}

// HealthCheck verifies the DeepInfra API is reachable and the API key is valid.
func (c *DeepInfraTTSClient) HealthCheck(ctx context.Context) error {
	// Use OpenAI-compatible /models endpoint
	req, err := http.NewRequestWithContext(ctx, "GET", DeepInfraBaseURL+"/models", nil)
	if err != nil {
		return fmt.Errorf("failed to create health check request: %w", err)
	}

	req.Header.Set("Authorization", "Bearer "+c.apiKey)

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

// Generate converts text to audio using DeepInfra's Chatterbox model.
func (c *DeepInfraTTSClient) Generate(ctx context.Context, req *TTSRequest) (*TTSResult, error) {
	start := time.Now()

	// Use request values or fall back to client defaults
	voice := req.Voice
	if voice == "" {
		voice = c.voice
	}
	format := req.Format
	if format == "" {
		format = c.format
	}

	// Build TTS request
	ttsReq := deepInfraTTSRequest{
		Text:           req.Text,
		ResponseFormat: format,
		Temperature:    c.temperature,
		Exaggeration:   c.exaggeration,
		CFG:            c.cfg,
	}
	if voice != "" {
		ttsReq.VoiceID = voice
	}

	// Make request
	resp, err := c.doRequest(ctx, ttsReq)
	if err != nil {
		return &TTSResult{
			Success:       false,
			ErrorMessage:  err.Error(),
			CharCount:     len(req.Text),
			ExecutionTime: time.Since(start),
		}, err
	}

	// Decode audio - handle both base64 and data URL formats
	var audio []byte
	var decodeErr error

	// Check if it's a data URL (e.g., "data:audio/mp3;base64,...")
	if strings.HasPrefix(resp.Audio, "data:") {
		// Extract base64 part after the comma
		if idx := strings.Index(resp.Audio, ","); idx != -1 {
			audio, decodeErr = base64.StdEncoding.DecodeString(resp.Audio[idx+1:])
		} else {
			decodeErr = fmt.Errorf("invalid data URL format")
		}
	} else {
		// Try standard base64 decoding
		audio, decodeErr = base64.StdEncoding.DecodeString(resp.Audio)
	}

	if decodeErr != nil {
		// Log the first 100 chars to help debug
		preview := resp.Audio
		if len(preview) > 100 {
			preview = preview[:100]
		}
		return &TTSResult{
			Success:       false,
			ErrorMessage:  fmt.Sprintf("failed to decode audio (preview: %q): %v", preview, decodeErr),
			CharCount:     len(req.Text),
			ExecutionTime: time.Since(start),
		}, fmt.Errorf("failed to decode audio: %w", decodeErr)
	}

	// Calculate duration from word timestamps if available
	durationMS := 0
	if len(resp.Words) > 0 {
		lastWord := resp.Words[len(resp.Words)-1]
		durationMS = int(lastWord.End * 1000) // Convert seconds to ms
	}

	// Get cost from inference status
	cost := 0.0
	if resp.InferenceStatus.Cost > 0 {
		cost = resp.InferenceStatus.Cost
	}

	return &TTSResult{
		Success:       true,
		Audio:         audio,
		DurationMS:    durationMS,
		Format:        format,
		CostUSD:       cost,
		CharCount:     resp.InputCharacterLength,
		ExecutionTime: time.Since(start),
	}, nil
}

// doRequest makes an HTTP request to DeepInfra TTS API.
func (c *DeepInfraTTSClient) doRequest(ctx context.Context, body deepInfraTTSRequest) (*deepInfraTTSResponse, error) {
	bodyBytes, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	endpoint := fmt.Sprintf("%s/%s", DeepInfraTTSInferenceEndpoint, c.model)
	req, err := http.NewRequestWithContext(ctx, "POST", endpoint, bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.apiKey)

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		var errResp deepInfraErrorResponse
		errMsg := string(respBody)
		if json.Unmarshal(respBody, &errResp) == nil && errResp.Error.Message != "" {
			errMsg = errResp.Error.Message
		}

		// Handle rate limiting with Retry-After header
		if resp.StatusCode == http.StatusTooManyRequests {
			retryAfter := parseRetryAfter(resp.Header.Get("Retry-After"))
			return nil, &RateLimitError{
				Message:    fmt.Sprintf("DeepInfra TTS rate limited: %s", errMsg),
				RetryAfter: retryAfter,
				StatusCode: resp.StatusCode,
			}
		}

		return nil, fmt.Errorf("DeepInfra TTS error (status %d): %s", resp.StatusCode, errMsg)
	}

	var ttsResp deepInfraTTSResponse
	if err := json.Unmarshal(respBody, &ttsResp); err != nil {
		return nil, fmt.Errorf("failed to unmarshal response: %w", err)
	}

	return &ttsResp, nil
}

// DeepInfra TTS API types

type deepInfraTTSRequest struct {
	Text              string  `json:"text"`
	ResponseFormat    string  `json:"response_format,omitempty"`
	VoiceID           string  `json:"voice_id,omitempty"`
	Temperature       float64 `json:"temperature,omitempty"`
	Exaggeration      float64 `json:"exaggeration,omitempty"`
	CFG               float64 `json:"cfg,omitempty"`
	TopP              float64 `json:"top_p,omitempty"`
	TopK              int     `json:"top_k,omitempty"`
	Seed              int     `json:"seed,omitempty"`
	MinP              float64 `json:"min_p,omitempty"`
	RepetitionPenalty float64 `json:"repetition_penalty,omitempty"`
}

type deepInfraTTSResponse struct {
	Audio                string            `json:"audio"` // Base64 encoded audio
	InputCharacterLength int               `json:"input_character_length"`
	OutputFormat         string            `json:"output_format"`
	Words                []deepInfraTTSWord `json:"words,omitempty"` // Word-level timestamps
	RequestID            string            `json:"request_id"`
	InferenceStatus      struct {
		Status          string  `json:"status"`
		RuntimeMS       int     `json:"runtime_ms"`
		Cost            float64 `json:"cost"`
		TokensGenerated int     `json:"tokens_generated"`
		TokensInput     int     `json:"tokens_input"`
	} `json:"inference_status"`
}

type deepInfraTTSWord struct {
	ID    int     `json:"id"`
	Start float64 `json:"start"` // Start time in seconds
	End   float64 `json:"end"`   // End time in seconds
	Text  string  `json:"text"`
}

// Model returns the model being used.
func (c *DeepInfraTTSClient) Model() string {
	return c.model
}

// Voice returns the default voice ID.
func (c *DeepInfraTTSClient) Voice() string {
	return c.voice
}

// Format returns the default output format.
func (c *DeepInfraTTSClient) Format() string {
	return c.format
}

// Voice represents a TTS voice from DeepInfra.
type Voice struct {
	VoiceID     string `json:"voice_id"`
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
	CreatedAt   string `json:"created_at,omitempty"`
}

// ListVoices retrieves available voices from DeepInfra.
func (c *DeepInfraTTSClient) ListVoices(ctx context.Context) ([]Voice, error) {
	// Voices endpoint is at /v1/voices, not under /v1/openai
	req, err := http.NewRequestWithContext(ctx, "GET", "https://api.deepinfra.com/v1/voices", nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Authorization", "Bearer "+c.apiKey)

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("failed to list voices (status %d): %s", resp.StatusCode, string(body))
	}

	var result struct {
		Voices []Voice `json:"voices"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return result.Voices, nil
}

// Verify interface
var _ TTSProvider = (*DeepInfraTTSClient)(nil)
