package providers

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

const (
	ElevenLabsTTSName      = "elevenlabs"
	ElevenLabsAPIBaseURL   = "https://api.elevenlabs.io/v1"
	ElevenLabsDefaultModel = "eleven_turbo_v2_5" // 40k char limit, 50% cheaper than multilingual_v2
)

// ElevenLabsTTSConfig holds configuration for the ElevenLabs TTS client.
type ElevenLabsTTSConfig struct {
	APIKey     string
	Model      string  // e.g., "eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_flash_v2_5"
	Voice      string  // Default voice ID
	Format     string  // Output format: mp3_44100_128, mp3_22050_32, pcm_16000, etc.
	Stability  float64 // Voice stability (0.0-1.0, default: 0.5)
	Similarity float64 // Similarity boost (0.0-1.0, default: 0.75)
	Style      float64 // Style exaggeration (0.0-1.0, default: 0.0)
	Speed      float64 // Speaking speed (0.7-1.2, default: 1.0)
	Timeout    time.Duration
	RateLimit  float64 // Requests per second
	MaxRetries int     // Max retry attempts (default: 3)
	RetryDelay time.Duration
}

// ElevenLabsTTSClient implements TTSProvider using ElevenLabs API.
type ElevenLabsTTSClient struct {
	apiKey     string
	model      string
	voice      string
	format     string
	stability  float64
	similarity float64
	style      float64
	speed      float64
	rateLimit  float64
	maxRetries int
	retryDelay time.Duration
	client     *http.Client
}

// NewElevenLabsTTSClient creates a new ElevenLabs TTS client.
func NewElevenLabsTTSClient(cfg ElevenLabsTTSConfig) *ElevenLabsTTSClient {
	if cfg.Model == "" {
		cfg.Model = ElevenLabsDefaultModel
	}
	if cfg.Format == "" {
		cfg.Format = "mp3_44100_128"
	}
	if cfg.Stability == 0 {
		cfg.Stability = 0.5
	}
	if cfg.Similarity == 0 {
		cfg.Similarity = 0.75
	}
	if cfg.Speed == 0 {
		cfg.Speed = 1.0
	}
	if cfg.Timeout == 0 {
		cfg.Timeout = 300 * time.Second // TTS can be slow for long text
	}
	if cfg.RateLimit == 0 {
		cfg.RateLimit = 10.0 // ElevenLabs Pro plan: 10 concurrent requests
	}
	if cfg.MaxRetries == 0 {
		cfg.MaxRetries = 3
	}
	if cfg.RetryDelay == 0 {
		cfg.RetryDelay = 2 * time.Second
	}

	return &ElevenLabsTTSClient{
		apiKey:     cfg.APIKey,
		model:      cfg.Model,
		voice:      cfg.Voice,
		format:     cfg.Format,
		stability:  cfg.Stability,
		similarity: cfg.Similarity,
		style:      cfg.Style,
		speed:      cfg.Speed,
		rateLimit:  cfg.RateLimit,
		maxRetries: cfg.MaxRetries,
		retryDelay: cfg.RetryDelay,
		client: &http.Client{
			Timeout: cfg.Timeout,
		},
	}
}

// Name returns the provider identifier.
func (c *ElevenLabsTTSClient) Name() string {
	return ElevenLabsTTSName
}

// RequestsPerSecond returns the rate limit.
func (c *ElevenLabsTTSClient) RequestsPerSecond() float64 {
	return c.rateLimit
}

// MaxConcurrency returns the max concurrent in-flight requests.
func (c *ElevenLabsTTSClient) MaxConcurrency() int {
	return 10 // ElevenLabs Pro plan allows 10 concurrent requests
}

// MaxRetries returns the maximum retry attempts.
func (c *ElevenLabsTTSClient) MaxRetries() int {
	return c.maxRetries
}

// RetryDelayBase returns the base delay for exponential backoff.
func (c *ElevenLabsTTSClient) RetryDelayBase() time.Duration {
	return c.retryDelay
}

// HealthCheck verifies the ElevenLabs API is reachable and the API key is valid.
func (c *ElevenLabsTTSClient) HealthCheck(ctx context.Context) error {
	// Use /user endpoint to verify API key
	req, err := http.NewRequestWithContext(ctx, "GET", ElevenLabsAPIBaseURL+"/user", nil)
	if err != nil {
		return fmt.Errorf("failed to create health check request: %w", err)
	}

	req.Header.Set("xi-api-key", c.apiKey)

	resp, err := c.client.Do(req)
	if err != nil {
		return fmt.Errorf("health check request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusUnauthorized {
		return fmt.Errorf("invalid API key")
	}
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("health check failed with status %d: %s", resp.StatusCode, string(body))
	}

	return nil
}

// Generate converts text to audio using ElevenLabs API.
func (c *ElevenLabsTTSClient) Generate(ctx context.Context, req *TTSRequest) (*TTSResult, error) {
	start := time.Now()

	// Use request values or fall back to client defaults
	voice := req.Voice
	if voice == "" {
		voice = c.voice
	}
	if voice == "" {
		return &TTSResult{
			Success:       false,
			ErrorMessage:  "voice_id is required",
			CharCount:     len(req.Text),
			ExecutionTime: time.Since(start),
		}, fmt.Errorf("voice_id is required")
	}

	format := req.Format
	if format == "" {
		format = c.format
	}

	// Build TTS request
	ttsReq := elevenLabsTTSRequest{
		Text:    req.Text,
		ModelID: c.model,
		VoiceSettings: elevenLabsVoiceSettings{
			Stability:       c.stability,
			SimilarityBoost: c.similarity,
			Style:           c.style,
			Speed:           c.speed,
			UseSpeakerBoost: true,
		},
		PreviousRequestIDs: req.PreviousRequestIDs, // For request stitching
	}

	// Make request
	audioBytes, requestID, err := c.doRequest(ctx, voice, format, ttsReq)
	if err != nil {
		return &TTSResult{
			Success:       false,
			ErrorMessage:  err.Error(),
			CharCount:     len(req.Text),
			ExecutionTime: time.Since(start),
		}, err
	}

	// ElevenLabs returns raw audio bytes directly
	// Duration estimation: ~150 words per minute, ~5 chars per word
	// This is approximate - for accurate duration, would need to decode audio
	estimatedDurationMS := (len(req.Text) * 60 * 1000) / (150 * 5)

	outputFormat, sampleRate := parseOutputFormat(format)

	// ElevenLabs pricing: ~$0.30 per 1000 characters for standard voices
	cost := float64(len(req.Text)) * 0.0003

	return &TTSResult{
		Success:       true,
		Audio:         audioBytes,
		DurationMS:    estimatedDurationMS,
		Format:        outputFormat,
		SampleRate:    sampleRate,
		CostUSD:       cost,
		CharCount:     len(req.Text),
		ExecutionTime: time.Since(start),
		RequestID:     requestID, // For request stitching
	}, nil
}

// doRequest makes an HTTP request to ElevenLabs TTS API.
// Returns the audio bytes and the request ID for stitching.
func (c *ElevenLabsTTSClient) doRequest(ctx context.Context, voiceID, format string, body elevenLabsTTSRequest) ([]byte, string, error) {
	bodyBytes, err := json.Marshal(body)
	if err != nil {
		return nil, "", fmt.Errorf("failed to marshal request: %w", err)
	}

	endpoint := fmt.Sprintf("%s/text-to-speech/%s?output_format=%s", ElevenLabsAPIBaseURL, voiceID, format)
	req, err := http.NewRequestWithContext(ctx, "POST", endpoint, bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, "", fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("xi-api-key", c.apiKey)

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, "", fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, "", fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		var errResp elevenLabsErrorResponse
		errMsg := string(respBody)
		if json.Unmarshal(respBody, &errResp) == nil && errResp.Detail.Message != "" {
			errMsg = errResp.Detail.Message
		}

		// Handle rate limiting
		if resp.StatusCode == http.StatusTooManyRequests {
			retryAfter := parseRetryAfter(resp.Header.Get("Retry-After"))
			return nil, "", &RateLimitError{
				Message:    fmt.Sprintf("ElevenLabs rate limited: %s", errMsg),
				RetryAfter: retryAfter,
				StatusCode: resp.StatusCode,
			}
		}

		return nil, "", fmt.Errorf("ElevenLabs TTS error (status %d): %s", resp.StatusCode, errMsg)
	}

	// Extract request ID from response header for request stitching.
	// ElevenLabs returns this as "request-id" or "x-request-id" header.
	requestID := resp.Header.Get("request-id")
	if requestID == "" {
		requestID = resp.Header.Get("x-request-id")
	}

	return respBody, requestID, nil
}

// ListVoices retrieves available voices from ElevenLabs.
func (c *ElevenLabsTTSClient) ListVoices(ctx context.Context) ([]Voice, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", ElevenLabsAPIBaseURL+"/voices", nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("xi-api-key", c.apiKey)

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("failed to list voices (status %d): %s", resp.StatusCode, string(body))
	}

	var result elevenLabsVoicesResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	// Convert to common Voice type
	voices := make([]Voice, 0, len(result.Voices))
	for _, v := range result.Voices {
		description := v.Description
		if description == "" && len(v.Labels) > 0 {
			// Build description from labels
			for key, val := range v.Labels {
				if description != "" {
					description += ", "
				}
				description += key + ": " + val
			}
		}

		voices = append(voices, Voice{
			VoiceID:     v.VoiceID,
			Name:        v.Name,
			Description: description,
		})
	}

	return voices, nil
}

// Model returns the model being used.
func (c *ElevenLabsTTSClient) Model() string {
	return c.model
}

// Voice returns the default voice ID.
func (c *ElevenLabsTTSClient) Voice() string {
	return c.voice
}

// Format returns the default output format.
func (c *ElevenLabsTTSClient) Format() string {
	return c.format
}

// ElevenLabs API types

type elevenLabsTTSRequest struct {
	Text               string                  `json:"text"`
	ModelID            string                  `json:"model_id"`
	VoiceSettings      elevenLabsVoiceSettings `json:"voice_settings"`
	PreviousRequestIDs []string                `json:"previous_request_ids,omitempty"` // For request stitching
}

type elevenLabsVoiceSettings struct {
	Stability       float64 `json:"stability"`
	SimilarityBoost float64 `json:"similarity_boost"`
	Style           float64 `json:"style,omitempty"`
	Speed           float64 `json:"speed,omitempty"`
	UseSpeakerBoost bool    `json:"use_speaker_boost,omitempty"`
}

// parseOutputFormat extracts container format and sample rate from output_format.
// Examples: mp3_44100_128 -> (mp3, 44100), pcm_16000 -> (wav, 16000).
func parseOutputFormat(format string) (container string, sampleRate int) {
	format = strings.ToLower(strings.TrimSpace(format))
	if format == "" {
		return "mp3", 0
	}

	parts := strings.Split(format, "_")
	container = parts[0]
	if container == "pcm" || container == "ulaw" || container == "alaw" {
		container = "wav"
	}

	if len(parts) >= 2 {
		if sr, err := strconv.Atoi(parts[1]); err == nil {
			sampleRate = sr
		}
	}

	return container, sampleRate
}

type elevenLabsErrorResponse struct {
	Detail struct {
		Status  string `json:"status"`
		Message string `json:"message"`
	} `json:"detail"`
}

type elevenLabsVoicesResponse struct {
	Voices []elevenLabsVoice `json:"voices"`
}

type elevenLabsVoice struct {
	VoiceID     string            `json:"voice_id"`
	Name        string            `json:"name"`
	Description string            `json:"description,omitempty"`
	Category    string            `json:"category,omitempty"`
	Labels      map[string]string `json:"labels,omitempty"`
}

// Verify interface
var _ TTSProvider = (*ElevenLabsTTSClient)(nil)
