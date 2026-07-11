package providers

import (
	"context"
	"fmt"
	"strings"
	"time"
)

const (
	ChandraOCRName  = "chandra"
	ChandraOCRModel = "datalab-to/chandra-ocr-2"

	// DefaultChandraOCRPrompt mirrors Chandra's ocr_layout prompt. The model is
	// trained to emit layout HTML; the provider converts that to Markdown after
	// inference so downstream stages get clean text while metadata keeps headers,
	// footers, and extracted image regions.
	DefaultChandraOCRPrompt = `OCR this image to HTML, arranged as layout blocks. Each layout block should be a div with the data-bbox attribute representing the bounding box of the block in x0 y0 x1 y1 format. Bboxes are normalized 0-1000. The data-label attribute is the label for the block.

Use the following labels:
- Caption
- Footnote
- Equation-Block
- List-Group
- Page-Header
- Page-Footer
- Image
- Section-Header
- Table
- Text
- Complex-Block
- Code-Block
- Form
- Table-Of-Contents
- Figure
- Chemical-Block
- Diagram
- Bibliography
- Blank-Page

Only use these tags ["math", "br", "i", "b", "u", "del", "sup", "sub", "table", "tr", "td", "p", "th", "div", "pre", "h1", "h2", "h3", "h4", "h5", "ul", "ol", "li", "input", "a", "span", "img", "hr", "tbody", "small", "caption", "strong", "thead", "big", "code", "chem"], and these attributes ["class", "colspan", "rowspan", "display", "checked", "type", "border", "value", "style", "href", "alt", "align", "data-bbox", "data-label"].
Guidelines:
* Inline math: Surround math with <math>...</math> tags. Math expressions should be rendered in KaTeX-compatible LaTeX. Use display for block math.
* Tables: Use colspan and rowspan attributes to match table structure.
* Formatting: Maintain consistent formatting with the image, including spacing, indentation, subscripts/superscripts, and special characters.
* Images: Include a description of any images in the alt attribute of an <img> tag. Do not fill out the src property. Describe in detail inside the div tag. Also convert charts to high fidelity data, and convert diagrams to mermaid.
* Maps, full-page figures, and dense diagrams: transcribe visible labels, titles, legends, and captions; include a concise summary in the relevant block. Do not produce exhaustive route-by-route prose or Mermaid for maps unless the source page itself contains a simple diagram that requires it.
* Blank or unreadable pages: If the page has no readable foreground text, or only bleed-through/shadow from the reverse side, emit a single layout block labeled Blank-Page and stop. Do not transcribe reverse-side bleed-through or describe scanner artifacts.
* Forms: Mark checkboxes and radio buttons properly.
* Text: join lines together properly into paragraphs using <p>...</p> tags. Use <br> tags for line breaks within paragraphs, but only when absolutely necessary to maintain meaning.
* Chemistry: Use <chem>...</chem> tags for chemical formulas with reactive SMILES.
* Lists: Preserve indents and proper list markers.
* Use the simplest possible HTML structure that accurately represents the content of the block.
* Make sure the text is accurate and easy for a human to read and interpret. Reading order should be correct and natural.`

	defaultChandraRPS            = 50.0
	defaultChandraMaxConcurrency = 16
	defaultChandraMaxRetries     = 5
	defaultChandraMaxTokens      = 12384
	defaultChandraTopP           = 0.1
	defaultChandraBboxScale      = 1000
)

// ChandraOCRConfig configures the Chandra OCR provider, a vision model served
// over an OpenAI-compatible chat API (e.g. `vllm serve datalab-to/chandra-ocr-2`).
type ChandraOCRConfig struct {
	Name                  string   // provider identity (default "chandra")
	BaseURLs              []string // self-hosted endpoints, least-busy first
	APIKey                string   // optional; sent only when non-empty
	Model                 string   // default datalab-to/chandra-ocr-2
	Prompt                string   // OCR instruction; default DefaultChandraOCRPrompt
	MaxOutputTokens       int
	IncludeImages         bool
	IncludeHeadersFooters bool
	Temperature           float64
	TopP                  float64
	RateLimit             float64
	MaxConcurrency        int
	MaxRetries            int
	RetryDelay            time.Duration
	Timeout               time.Duration
}

// ChandraOCRClient implements OCRProvider by sending each page image plus an OCR
// prompt to a Chandra vision model and returning the Markdown transcription.
// It wraps an OpenAI-compatible chat client, reusing its transport, endpoint
// load-balancing, and retry machinery.
type ChandraOCRClient struct {
	name                  string
	model                 string
	prompt                string
	maxOutputTokens       int
	includeImages         bool
	includeHeadersFooters bool
	temperature           float64
	topP                  float64
	llm                   *OpenAIChatClient
	rateLimit             float64
	maxConcurrency        int
	maxRetries            int
	retryDelay            time.Duration
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
	if cfg.MaxOutputTokens == 0 {
		cfg.MaxOutputTokens = defaultChandraMaxTokens
	}
	if cfg.TopP == 0 {
		cfg.TopP = defaultChandraTopP
	}
	if cfg.RetryDelay == 0 {
		cfg.RetryDelay = 2 * time.Second
	}

	llm := NewOpenAICompatClient(OpenAICompatConfig{
		Name:           name,
		BaseURLs:       cfg.BaseURLs,
		APIKey:         cfg.APIKey,
		DefaultModel:   cfg.Model,
		RPS:            cfg.RateLimit,
		MaxConcurrency: cfg.MaxConcurrency,
		MaxRetries:     cfg.MaxRetries,
		RetryDelay:     cfg.RetryDelay,
		Timeout:        cfg.Timeout,
	})

	return &ChandraOCRClient{
		name:                  name,
		model:                 cfg.Model,
		prompt:                cfg.Prompt,
		maxOutputTokens:       cfg.MaxOutputTokens,
		includeImages:         cfg.IncludeImages,
		includeHeadersFooters: cfg.IncludeHeadersFooters,
		temperature:           cfg.Temperature,
		topP:                  cfg.TopP,
		llm:                   llm,
		rateLimit:             cfg.RateLimit,
		maxConcurrency:        cfg.MaxConcurrency,
		maxRetries:            cfg.MaxRetries,
		retryDelay:            cfg.RetryDelay,
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

// ManagesRetries reports that the wrapped OpenAI-compatible client consumes
// the configured retry budget inside ProcessImage.
func (c *ChandraOCRClient) ManagesRetries() bool { return true }

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
		Temperature:    c.temperature,
		TemperatureSet: true,
		TopP:           c.topP,
		MaxTokens:      c.maxOutputTokens,
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

	page, parseErr := parseChandraLayoutHTML(res.Content, image, pageNum, chandraParseOptions{
		IncludeImages:         c.includeImages,
		IncludeHeadersFooters: c.includeHeadersFooters,
	})
	if parseErr != nil {
		return &OCRResult{
			Success:       false,
			ExecutionTime: time.Since(start),
			ErrorMessage:  parseErr.Error(),
		}, fmt.Errorf("chandra OCR post-processing failed (page %d): %w", pageNum, parseErr)
	}

	return &OCRResult{
		Success:       true,
		Text:          page.Markdown,
		Header:        strings.Join(page.Headers, "\n"),
		Footer:        strings.Join(page.Footers, "\n"),
		CostUSD:       0, // local inference; see ADR 011
		ExecutionTime: time.Since(start),
		Metadata: map[string]any{
			"model":             res.ModelUsed,
			"prompt_tokens":     res.PromptTokens,
			"completion_tokens": res.CompletionTokens,
			"raw_layout_chars":  len(res.Content),
			"markdown_chars":    len(page.Markdown),
			"page_headers":      page.Headers,
			"page_footers":      page.Footers,
			"images":            page.Images,
		},
	}, nil
}

var _ OCRProvider = (*ChandraOCRClient)(nil)
