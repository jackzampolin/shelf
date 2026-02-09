package providers

import (
	"context"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"strings"
	"time"

	openai "github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/option"
)

const (
	OpenAITTSName         = "openai"
	openAITTSDefaultModel = openai.SpeechModelTTS1HD
	openAITTSDefaultVoice = "onyx"

	// Pricing approximations used because AudioSpeech responses do not include usage.
	// Values represent USD per 1M tokens.
	openAIGPT4oMiniTTSInputCostPer1M       = 0.60
	openAIGPT4oMiniTTSOutputAudioCostPer1M = 12.00
)

// OpenAITTSConfig holds configuration for the OpenAI TTS client.
type OpenAITTSConfig struct {
	APIKey       string
	Model        string        // "tts-1-hd" (default), "tts-1", "gpt-4o-mini-tts"
	Voice        string        // "onyx" (default)
	Speed        float64       // 0.25-4.0
	Instructions string        // Used by gpt-4o-mini-tts
	RateLimit    float64       // Requests per second
	MaxRetries   int           // Retry attempts for SDK transport
	RetryDelay   time.Duration // Base retry delay for worker backoff
	Timeout      time.Duration // HTTP timeout
	BaseURL      string        // Optional (tests)
	HTTPClient   *http.Client  // Optional (tests)
}

// OpenAITTSClient implements TTSProvider using the official OpenAI SDK.
type OpenAITTSClient struct {
	apiKey       string
	model        string
	voice        string
	speed        float64
	instructions string
	rateLimit    float64
	maxRetries   int
	retryDelay   time.Duration
	client       openai.Client
}

// NewOpenAITTSClient creates a new OpenAI TTS client.
func NewOpenAITTSClient(cfg OpenAITTSConfig) *OpenAITTSClient {
	if cfg.Model == "" {
		cfg.Model = openAITTSDefaultModel
	}
	if cfg.Voice == "" {
		cfg.Voice = openAITTSDefaultVoice
	}
	if cfg.Speed <= 0 {
		cfg.Speed = 1.0
	}
	if cfg.RateLimit <= 0 {
		// Default to ~500 RPM.
		cfg.RateLimit = 8.0
	}
	if cfg.MaxRetries <= 0 {
		cfg.MaxRetries = 3
	}
	if cfg.RetryDelay == 0 {
		cfg.RetryDelay = 2 * time.Second
	}
	if cfg.Timeout == 0 {
		cfg.Timeout = 300 * time.Second
	}

	httpClient := cfg.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{Timeout: cfg.Timeout}
	}

	opts := []option.RequestOption{
		option.WithAPIKey(cfg.APIKey),
		option.WithHTTPClient(httpClient),
		option.WithMaxRetries(cfg.MaxRetries),
	}
	if cfg.BaseURL != "" {
		opts = append(opts, option.WithBaseURL(cfg.BaseURL))
	}

	client := openai.NewClient(opts...)

	return &OpenAITTSClient{
		apiKey:       cfg.APIKey,
		model:        cfg.Model,
		voice:        cfg.Voice,
		speed:        cfg.Speed,
		instructions: cfg.Instructions,
		rateLimit:    cfg.RateLimit,
		maxRetries:   cfg.MaxRetries,
		retryDelay:   cfg.RetryDelay,
		client:       client,
	}
}

// Name returns the provider identifier.
func (c *OpenAITTSClient) Name() string {
	return OpenAITTSName
}

// RequestsPerSecond returns the configured rate limit.
func (c *OpenAITTSClient) RequestsPerSecond() float64 {
	return c.rateLimit
}

// MaxConcurrency returns max concurrent in-flight requests.
func (c *OpenAITTSClient) MaxConcurrency() int {
	// OpenAI limits vary by account tier; use generic default pool size.
	return 0
}

// MaxRetries returns the maximum retry attempts.
func (c *OpenAITTSClient) MaxRetries() int {
	return c.maxRetries
}

// RetryDelayBase returns the base delay for exponential backoff.
func (c *OpenAITTSClient) RetryDelayBase() time.Duration {
	return c.retryDelay
}

// HealthCheck verifies the OpenAI API is reachable and the API key is valid.
func (c *OpenAITTSClient) HealthCheck(ctx context.Context) error {
	page, err := c.client.Models.List(ctx)
	if err != nil {
		return fmt.Errorf("openai models list failed: %w", mapOpenAIError(err))
	}
	if page == nil {
		return fmt.Errorf("openai models list returned nil response")
	}
	return nil
}

// Generate converts text to audio using OpenAI TTS API.
func (c *OpenAITTSClient) Generate(ctx context.Context, req *TTSRequest) (*TTSResult, error) {
	start := time.Now()

	if req == nil {
		err := fmt.Errorf("request is required")
		return &TTSResult{
			Success:       false,
			ErrorMessage:  err.Error(),
			ExecutionTime: time.Since(start),
		}, err
	}

	text := strings.TrimSpace(req.Text)
	if text == "" {
		err := fmt.Errorf("text is required")
		return &TTSResult{
			Success:       false,
			ErrorMessage:  err.Error(),
			ExecutionTime: time.Since(start),
		}, err
	}

	voice := strings.TrimSpace(req.Voice)
	if voice == "" {
		voice = c.voice
	}
	if voice == "" {
		voice = openAITTSDefaultVoice
	}

	format := normalizeOpenAIFormat(req.Format)
	params := openai.AudioSpeechNewParams{
		Input:          text,
		Model:          openai.SpeechModel(c.model),
		Voice:          openai.AudioSpeechNewParamsVoice(voice),
		ResponseFormat: format,
		Speed:          openai.Float(c.speed),
	}

	instructions := strings.TrimSpace(req.Instructions)
	if instructions == "" {
		instructions = strings.TrimSpace(c.instructions)
	}
	if instructions != "" && supportsInstructions(c.model) {
		params.Instructions = openai.String(instructions)
	}

	resp, err := c.client.Audio.Speech.New(ctx, params)
	if err != nil {
		err = mapOpenAIError(err)
		return &TTSResult{
			Success:       false,
			ErrorMessage:  err.Error(),
			CharCount:     len(text),
			ExecutionTime: time.Since(start),
		}, err
	}
	defer resp.Body.Close()

	audioBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		err = fmt.Errorf("failed reading openai audio response: %w", err)
		return &TTSResult{
			Success:       false,
			ErrorMessage:  err.Error(),
			CharCount:     len(text),
			ExecutionTime: time.Since(start),
		}, err
	}

	// Rough duration estimate to align with existing providers.
	estimatedDurationMS := (len(text) * 60 * 1000) / (150 * 5)
	costUSD := estimateOpenAITTSCostUSD(c.model, text, estimatedDurationMS)

	return &TTSResult{
		Success:       true,
		Audio:         audioBytes,
		DurationMS:    estimatedDurationMS,
		Format:        openAIResultFormat(format),
		SampleRate:    0,
		CostUSD:       costUSD,
		CharCount:     len(text),
		ExecutionTime: time.Since(start),
		RequestID:     "", // OpenAI TTS does not provide request-stitching IDs.
	}, nil
}

func estimateOpenAITTSCostUSD(model, text string, durationMS int) float64 {
	model = strings.TrimSpace(strings.ToLower(model))
	switch model {
	case "tts-1-hd":
		return float64(len(text)) * (0.03 / 1000.0)
	case "tts-1":
		return float64(len(text)) * (0.015 / 1000.0)
	default:
		// gpt-4o-mini-tts uses token pricing; approximate from text length and estimated audio duration.
		if strings.HasPrefix(model, "gpt-4o-mini-tts") {
			textTokens := estimateTextTokens(text)
			audioTokens := estimateAudioTokens(durationMS)
			inputCost := float64(textTokens) * (openAIGPT4oMiniTTSInputCostPer1M / 1_000_000.0)
			outputCost := float64(audioTokens) * (openAIGPT4oMiniTTSOutputAudioCostPer1M / 1_000_000.0)
			return inputCost + outputCost
		}
		// Unknown OpenAI speech model: fall back to tts-1 estimate instead of returning zero.
		return float64(len(text)) * (0.015 / 1000.0)
	}
}

func estimateTextTokens(text string) int {
	runes := len([]rune(strings.TrimSpace(text)))
	if runes == 0 {
		return 0
	}
	return int(math.Ceil(float64(runes) / 4.0))
}

func estimateAudioTokens(durationMS int) int {
	if durationMS <= 0 {
		return 0
	}
	// Approximate OpenAI audio token density (~50 tokens/sec).
	seconds := float64(durationMS) / 1000.0
	return int(math.Ceil(seconds * 50.0))
}

// ListVoices returns the built-in OpenAI TTS voice list.
func (c *OpenAITTSClient) ListVoices(_ context.Context) ([]Voice, error) {
	names := []string{
		"alloy", "ash", "ballad", "coral", "echo", "fable", "nova",
		"onyx", "sage", "shimmer", "verse", "marin", "cedar",
	}

	voices := make([]Voice, 0, len(names))
	for _, name := range names {
		voices = append(voices, Voice{
			VoiceID: name,
			Name:    name,
		})
	}
	return voices, nil
}

func supportsInstructions(model string) bool {
	m := strings.ToLower(strings.TrimSpace(model))
	return strings.HasPrefix(m, "gpt-4o-mini-tts")
}

func normalizeOpenAIFormat(format string) openai.AudioSpeechNewParamsResponseFormat {
	switch strings.ToLower(strings.TrimSpace(format)) {
	case "", "mp3", "mp3_44100_128":
		return openai.AudioSpeechNewParamsResponseFormatMP3
	case "opus":
		return openai.AudioSpeechNewParamsResponseFormatOpus
	case "aac":
		return openai.AudioSpeechNewParamsResponseFormatAAC
	case "flac":
		return openai.AudioSpeechNewParamsResponseFormatFLAC
	case "wav":
		return openai.AudioSpeechNewParamsResponseFormatWAV
	case "pcm":
		return openai.AudioSpeechNewParamsResponseFormatPCM
	default:
		return openai.AudioSpeechNewParamsResponseFormatMP3
	}
}

func openAIResultFormat(format openai.AudioSpeechNewParamsResponseFormat) string {
	switch format {
	case openai.AudioSpeechNewParamsResponseFormatOpus:
		return "opus"
	case openai.AudioSpeechNewParamsResponseFormatAAC:
		return "aac"
	case openai.AudioSpeechNewParamsResponseFormatFLAC:
		return "flac"
	case openai.AudioSpeechNewParamsResponseFormatWAV:
		return "wav"
	case openai.AudioSpeechNewParamsResponseFormatPCM:
		return "wav"
	default:
		return "mp3"
	}
}

func mapOpenAIError(err error) error {
	var apiErr *openai.Error
	if errors.As(err, &apiErr) {
		if apiErr.StatusCode == http.StatusTooManyRequests {
			retryAfter := time.Duration(0)
			if apiErr.Response != nil {
				retryAfter = parseRetryAfter(apiErr.Response.Header.Get("Retry-After"))
			}
			return &RateLimitError{
				Message:    fmt.Sprintf("OpenAI rate limited: %s", apiErr.Message),
				RetryAfter: retryAfter,
				StatusCode: apiErr.StatusCode,
			}
		}
		if apiErr.Message != "" {
			return fmt.Errorf("OpenAI TTS error (status %d): %s", apiErr.StatusCode, apiErr.Message)
		}
		return fmt.Errorf("OpenAI TTS error (status %d)", apiErr.StatusCode)
	}
	return err
}

// Model returns the configured default model.
func (c *OpenAITTSClient) Model() string {
	return c.model
}

// Voice returns the configured default voice.
func (c *OpenAITTSClient) Voice() string {
	return c.voice
}

// Instructions returns the configured default instructions.
func (c *OpenAITTSClient) Instructions() string {
	return c.instructions
}

var _ TTSProvider = (*OpenAITTSClient)(nil)
var _ VoicesLister = (*OpenAITTSClient)(nil)
