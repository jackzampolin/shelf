package providers

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

const (
	MistralOCRName    = "mistral-ocr"
	MistralOCRBaseURL = "https://api.mistral.ai/v1"
	MistralOCRModel   = "mistral-ocr-latest"

	// Mistral OCR pricing: $1/1000 pages base + $3/1000 pages for annotations
	// Actual cost averages ~$0.0012 per page since not all pages have images
	MistralOCRCostPerPage = 0.0012
)

// MistralOCRConfig holds configuration for the Mistral OCR client.
type MistralOCRConfig struct {
	APIKey        string
	BaseURL       string
	Model         string
	Timeout       time.Duration
	IncludeImages bool    // Whether to include base64 image data in response
	RateLimit     float64 // Requests per second (default: 6.0)
}

// MistralOCRClient implements OCRProvider using the Mistral OCR API.
type MistralOCRClient struct {
	apiKey        string
	baseURL       string
	model         string
	includeImages bool
	rateLimit     float64
	client        *http.Client
}

// NewMistralOCRClient creates a new Mistral OCR client.
func NewMistralOCRClient(cfg MistralOCRConfig) *MistralOCRClient {
	if cfg.BaseURL == "" {
		cfg.BaseURL = MistralOCRBaseURL
	}
	if cfg.Model == "" {
		cfg.Model = MistralOCRModel
	}
	if cfg.Timeout == 0 {
		cfg.Timeout = 120 * time.Second
	}
	if cfg.RateLimit == 0 {
		cfg.RateLimit = 6.0 // Mistral OCR default rate limit
	}

	return &MistralOCRClient{
		apiKey:        cfg.APIKey,
		baseURL:       cfg.BaseURL,
		model:         cfg.Model,
		includeImages: cfg.IncludeImages,
		rateLimit:     cfg.RateLimit,
		client: &http.Client{
			Timeout: cfg.Timeout,
		},
	}
}

// Name returns the provider identifier.
func (c *MistralOCRClient) Name() string {
	return MistralOCRName
}

// RequestsPerSecond returns the rate limit for Mistral OCR.
func (c *MistralOCRClient) RequestsPerSecond() float64 {
	return c.rateLimit
}

// MaxRetries returns the maximum retry attempts.
func (c *MistralOCRClient) MaxRetries() int {
	return 3
}

// RetryDelayBase returns the base delay for exponential backoff.
func (c *MistralOCRClient) RetryDelayBase() time.Duration {
	return 2 * time.Second
}

// ProcessImage extracts text from an image using Mistral OCR.
func (c *MistralOCRClient) ProcessImage(ctx context.Context, image []byte, pageNum int) (*OCRResult, error) {
	start := time.Now()

	// Encode image to base64
	imageBase64 := base64.StdEncoding.EncodeToString(image)

	// Build request
	reqBody := mistralOCRRequest{
		Model: c.model,
		Document: mistralDocument{
			Type: "image_url",
			ImageURL: &mistralImageURL{
				URL: "data:image/png;base64," + imageBase64,
			},
		},
		IncludeImageBase64: c.includeImages,
	}

	// Make request
	resp, err := c.doRequest(ctx, "/ocr", reqBody)
	if err != nil {
		return &OCRResult{
			Success:       false,
			ErrorMessage:  err.Error(),
			ExecutionTime: time.Since(start),
		}, err
	}

	// Check response has pages
	if len(resp.Pages) == 0 {
		return &OCRResult{
			Success:       false,
			ErrorMessage:  "no pages in OCR response",
			ExecutionTime: time.Since(start),
		}, fmt.Errorf("no pages in OCR response")
	}

	// Get first page (single image = single page)
	page := resp.Pages[0]

	// Build metadata
	metadata := map[string]any{
		"model_used": resp.Model,
		"dimensions": map[string]any{
			"width":  page.Dimensions.Width,
			"height": page.Dimensions.Height,
			"dpi":    page.Dimensions.DPI,
		},
		"page_index": page.Index,
	}

	// Add image bounding boxes if present
	if len(page.Images) > 0 {
		images := make([]map[string]any, len(page.Images))
		for i, img := range page.Images {
			images[i] = map[string]any{
				"id":             img.ID,
				"top_left_x":     img.TopLeftX,
				"top_left_y":     img.TopLeftY,
				"bottom_right_x": img.BottomRightX,
				"bottom_right_y": img.BottomRightY,
			}
			if img.ImageBase64 != "" {
				images[i]["has_base64"] = true
			}
		}
		metadata["images"] = images
	}

	// Add usage info
	if resp.UsageInfo != nil {
		metadata["pages_processed"] = resp.UsageInfo.PagesProcessed
		if resp.UsageInfo.DocSizeBytes > 0 {
			metadata["doc_size_bytes"] = resp.UsageInfo.DocSizeBytes
		}
	}

	return &OCRResult{
		Success:       true,
		Text:          page.Markdown,
		Metadata:      metadata,
		CostUSD:       MistralOCRCostPerPage,
		ExecutionTime: time.Since(start),
	}, nil
}

// doRequest makes an HTTP request to Mistral API.
func (c *MistralOCRClient) doRequest(ctx context.Context, path string, body any) (*mistralOCRResponse, error) {
	bodyBytes, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+path, bytes.NewReader(bodyBytes))
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
		// Try to extract error message from response
		var errResp mistralErrorResponse
		if json.Unmarshal(respBody, &errResp) == nil && errResp.Error.Message != "" {
			return nil, fmt.Errorf("Mistral OCR error (status %d): %s", resp.StatusCode, errResp.Error.Message)
		}
		return nil, fmt.Errorf("Mistral OCR error (status %d): %s", resp.StatusCode, string(respBody))
	}

	var ocrResp mistralOCRResponse
	if err := json.Unmarshal(respBody, &ocrResp); err != nil {
		return nil, fmt.Errorf("failed to unmarshal response: %w", err)
	}

	return &ocrResp, nil
}

// Mistral OCR API types

type mistralOCRRequest struct {
	Model              string          `json:"model"`
	Document           mistralDocument `json:"document"`
	IncludeImageBase64 bool            `json:"include_image_base64,omitempty"`
	Pages              []int           `json:"pages,omitempty"`
	ImageLimit         int             `json:"image_limit,omitempty"`
	ImageMinSize       int             `json:"image_min_size,omitempty"`
}

type mistralDocument struct {
	Type        string           `json:"type"` // "image_url" or "document_url"
	ImageURL    *mistralImageURL `json:"image_url,omitempty"`
	DocumentURL string           `json:"document_url,omitempty"`
}

type mistralImageURL struct {
	URL    string `json:"url"`
	Detail string `json:"detail,omitempty"` // "auto", "low", "high"
}

type mistralOCRResponse struct {
	Model              string            `json:"model"`
	Pages              []mistralOCRPage  `json:"pages"`
	DocumentAnnotation string            `json:"document_annotation,omitempty"`
	UsageInfo          *mistralUsageInfo `json:"usage_info,omitempty"`
}

type mistralOCRPage struct {
	Index      int                   `json:"index"`
	Markdown   string                `json:"markdown"`
	Images     []mistralOCRImage     `json:"images,omitempty"`
	Dimensions mistralPageDimensions `json:"dimensions"`
}

type mistralOCRImage struct {
	ID              string `json:"id"`
	TopLeftX        int    `json:"top_left_x"`
	TopLeftY        int    `json:"top_left_y"`
	BottomRightX    int    `json:"bottom_right_x"`
	BottomRightY    int    `json:"bottom_right_y"`
	ImageBase64     string `json:"image_base64,omitempty"`
	ImageAnnotation string `json:"image_annotation,omitempty"`
}

type mistralPageDimensions struct {
	Width  int `json:"width"`
	Height int `json:"height"`
	DPI    int `json:"dpi"`
}

type mistralUsageInfo struct {
	PagesProcessed int `json:"pages_processed"`
	DocSizeBytes   int `json:"doc_size_bytes,omitempty"`
}

type mistralErrorResponse struct {
	Error struct {
		Message string `json:"message"`
		Type    string `json:"type"`
	} `json:"error"`
}

// Verify interface
var _ OCRProvider = (*MistralOCRClient)(nil)
