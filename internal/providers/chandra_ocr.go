package providers

import (
	"bytes"
	"context"
	"encoding/base64"
	"fmt"
	"image"
	"image/jpeg"
	_ "image/png"
	"regexp"
	"strconv"
	"strings"
	"time"

	stdhtml "html"

	nethtml "golang.org/x/net/html"
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
	BaseURLs              []string // self-hosted endpoints, round-robined
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
// It wraps an OpenAI-compatible chat client, reusing its transport, round-robin,
// and retry machinery.
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

type chandraParseOptions struct {
	IncludeImages         bool
	IncludeHeadersFooters bool
}

type chandraParsedPage struct {
	Markdown string
	Headers  []string
	Footers  []string
	Images   []map[string]any
}

type chandraLayoutBlock struct {
	Label string
	BBox  [4]int
	Node  *nethtml.Node
}

func parseChandraLayoutHTML(raw string, imageBytes []byte, pageNum int, opts chandraParseOptions) (chandraParsedPage, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return chandraParsedPage{}, nil
	}

	blocks, err := parseChandraLayoutBlocks(raw)
	if err != nil {
		return chandraParsedPage{}, err
	}
	if len(blocks) == 0 {
		return chandraParsedPage{Markdown: raw}, nil
	}

	var pageImage image.Image
	if opts.IncludeImages {
		pageImage, _, _ = image.Decode(bytes.NewReader(imageBytes))
	}

	var parts []string
	var headers []string
	var footers []string
	var images []map[string]any
	imageIndex := 0

	for _, block := range blocks {
		label := strings.TrimSpace(block.Label)
		blockText := strings.TrimSpace(renderChandraMarkdownChildren(block.Node))
		blockPlainText := strings.TrimSpace(textContent(block.Node))

		switch label {
		case "Blank-Page":
			continue
		case "Page-Header":
			if blockPlainText != "" {
				headers = append(headers, blockPlainText)
			}
			if !opts.IncludeHeadersFooters {
				continue
			}
		case "Page-Footer":
			if blockPlainText != "" {
				footers = append(footers, blockPlainText)
			}
			if !opts.IncludeHeadersFooters {
				continue
			}
		case "Image", "Figure":
			if !opts.IncludeImages {
				continue
			}
			alt := chandraImageAlt(block.Node)
			if alt == "" {
				alt = strings.TrimSpace(textContent(block.Node))
			}
			if alt == "" {
				alt = label
			}
			if isChandraBlankImage(alt) {
				continue
			}
			imageIndex++
			imageID := fmt.Sprintf("chandra-page-%04d-image-%02d.jpg", pageNum, imageIndex)
			parts = append(parts, fmt.Sprintf("![%s](%s)", escapeMarkdownAlt(alt), imageID))
			if imgMeta := chandraExtractImageMetadata(pageImage, block, imageID, alt); imgMeta != nil {
				images = append(images, imgMeta)
			}
			continue
		}

		if label == "Section-Header" && blockText != "" && !strings.HasPrefix(strings.TrimSpace(blockText), "#") {
			blockText = "## " + strings.TrimSpace(stripMarkdownEmphasis(blockText))
		}
		blockText = cleanChandraTextArtifacts(blockText)
		if blockText != "" {
			parts = append(parts, blockText)
		}
	}

	return chandraParsedPage{
		Markdown: joinMarkdownBlocks(parts),
		Headers:  headers,
		Footers:  footers,
		Images:   images,
	}, nil
}

func parseChandraLayoutBlocks(raw string) ([]chandraLayoutBlock, error) {
	nodes, err := nethtml.ParseFragment(strings.NewReader(raw), nil)
	if err != nil {
		return nil, fmt.Errorf("failed to parse Chandra layout HTML: %w", err)
	}

	var blocks []chandraLayoutBlock
	for _, node := range nodes {
		collectChandraLayoutBlocks(node, &blocks)
	}
	return blocks, nil
}

func collectChandraLayoutBlocks(node *nethtml.Node, blocks *[]chandraLayoutBlock) {
	if node == nil {
		return
	}
	if node.Type == nethtml.ElementNode && node.Data == "div" {
		if label := attrValue(node, "data-label"); label != "" {
			*blocks = append(*blocks, chandraLayoutBlock{
				Label: label,
				BBox:  parseChandraBBox(attrValue(node, "data-bbox")),
				Node:  node,
			})
			return
		}
	}
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		collectChandraLayoutBlocks(child, blocks)
	}
}

func parseChandraBBox(raw string) [4]int {
	var bbox [4]int
	fields := strings.Fields(raw)
	if len(fields) != 4 {
		return bbox
	}
	for i, field := range fields {
		n, err := strconv.Atoi(field)
		if err != nil {
			return [4]int{}
		}
		bbox[i] = n
	}
	return bbox
}

func renderChandraMarkdownChildren(node *nethtml.Node) string {
	if node == nil {
		return ""
	}
	var parts []string
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		parts = append(parts, renderChandraMarkdownNode(child))
	}
	return cleanMarkdownSpacing(strings.Join(parts, ""))
}

func renderChandraMarkdownNode(node *nethtml.Node) string {
	if node == nil {
		return ""
	}
	switch node.Type {
	case nethtml.TextNode:
		return stdhtml.UnescapeString(node.Data)
	case nethtml.ElementNode:
		tag := strings.ToLower(node.Data)
		switch tag {
		case "br":
			return "  \n"
		case "p":
			return strings.TrimSpace(renderChandraMarkdownChildren(node)) + "\n\n"
		case "h1", "h2", "h3", "h4", "h5", "h6":
			level := int(tag[1] - '0')
			return strings.Repeat("#", level) + " " + strings.TrimSpace(stripMarkdownEmphasis(renderChandraMarkdownChildren(node))) + "\n\n"
		case "i", "em":
			text := strings.TrimSpace(renderChandraMarkdownChildren(node))
			if text == "" {
				return ""
			}
			return "*" + text + "*"
		case "b", "strong":
			text := strings.TrimSpace(renderChandraMarkdownChildren(node))
			if text == "" {
				return ""
			}
			return "**" + text + "**"
		case "sup", "sub", "math", "chem":
			text := strings.TrimSpace(renderChandraMarkdownChildren(node))
			if text == "" {
				return ""
			}
			return "<" + tag + ">" + text + "</" + tag + ">"
		case "ul", "ol":
			return renderListMarkdown(node, tag == "ol") + "\n"
		case "li":
			return strings.TrimSpace(renderChandraMarkdownChildren(node))
		case "pre":
			return "```\n" + strings.TrimSpace(textContent(node)) + "\n```\n\n"
		case "code":
			return "`" + strings.TrimSpace(textContent(node)) + "`"
		case "table":
			return "\n\n" + renderCleanHTML(node) + "\n\n"
		case "img":
			alt := attrValue(node, "alt")
			src := attrValue(node, "src")
			if src == "" {
				return strings.TrimSpace(alt)
			}
			return fmt.Sprintf("![%s](%s)", escapeMarkdownAlt(alt), src)
		default:
			return renderChandraMarkdownChildren(node)
		}
	default:
		return ""
	}
}

func renderListMarkdown(node *nethtml.Node, ordered bool) string {
	var lines []string
	idx := 1
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		if child.Type != nethtml.ElementNode || strings.ToLower(child.Data) != "li" {
			continue
		}
		prefix := "- "
		if ordered {
			prefix = fmt.Sprintf("%d. ", idx)
			idx++
		}
		lines = append(lines, prefix+strings.TrimSpace(renderChandraMarkdownChildren(child)))
	}
	return strings.Join(lines, "\n")
}

func cleanMarkdownSpacing(text string) string {
	text = strings.ReplaceAll(text, "\r\n", "\n")
	text = strings.ReplaceAll(text, "\r", "\n")
	spaceRe := regexp.MustCompile(`[ \t]+`)
	lines := strings.Split(text, "\n")
	for i, line := range lines {
		lines[i] = strings.TrimRight(spaceRe.ReplaceAllString(line, " "), " ")
	}
	text = strings.Join(lines, "\n")
	blankRe := regexp.MustCompile(`\n{3,}`)
	return strings.TrimSpace(blankRe.ReplaceAllString(text, "\n\n"))
}

func joinMarkdownBlocks(parts []string) string {
	cleaned := make([]string, 0, len(parts))
	for _, part := range parts {
		part = cleanMarkdownSpacing(part)
		if part != "" {
			cleaned = append(cleaned, part)
		}
	}
	return strings.Join(cleaned, "\n\n")
}

func renderCleanHTML(node *nethtml.Node) string {
	var b strings.Builder
	renderCleanHTMLNode(&b, node)
	return b.String()
}

func renderCleanHTMLNode(b *strings.Builder, node *nethtml.Node) {
	if node == nil {
		return
	}
	switch node.Type {
	case nethtml.TextNode:
		b.WriteString(escapeHTMLText(stdhtml.UnescapeString(node.Data)))
	case nethtml.ElementNode:
		tag := strings.ToLower(node.Data)
		b.WriteByte('<')
		b.WriteString(tag)
		for _, attr := range node.Attr {
			key := strings.ToLower(attr.Key)
			if strings.HasPrefix(key, "data-") || key == "class" || key == "style" {
				continue
			}
			b.WriteByte(' ')
			b.WriteString(key)
			b.WriteString(`="`)
			b.WriteString(stdhtml.EscapeString(attr.Val))
			b.WriteByte('"')
		}
		b.WriteByte('>')
		for child := node.FirstChild; child != nil; child = child.NextSibling {
			renderCleanHTMLNode(b, child)
		}
		b.WriteString("</")
		b.WriteString(tag)
		b.WriteByte('>')
	}
}

func escapeHTMLText(text string) string {
	text = strings.ReplaceAll(text, "&", "&amp;")
	text = strings.ReplaceAll(text, "<", "&lt;")
	text = strings.ReplaceAll(text, ">", "&gt;")
	return text
}

func isChandraBlankImage(alt string) bool {
	normalized := strings.ToLower(strings.Join(strings.Fields(alt), " "))
	switch normalized {
	case "blank page", "blank white page", "blank image", "white page":
		return true
	default:
		return strings.Contains(normalized, "blank white page")
	}
}

func cleanChandraTextArtifacts(text string) string {
	normalized := strings.ToLower(strings.Join(strings.Fields(stripMarkdownEmphasis(text)), " "))
	if matched, _ := regexp.MatchString(`^picture at page \d+$`, normalized); matched {
		return ""
	}
	return text
}

func chandraImageAlt(node *nethtml.Node) string {
	var find func(*nethtml.Node) string
	find = func(n *nethtml.Node) string {
		if n == nil {
			return ""
		}
		if n.Type == nethtml.ElementNode && strings.ToLower(n.Data) == "img" {
			return strings.TrimSpace(attrValue(n, "alt"))
		}
		for child := n.FirstChild; child != nil; child = child.NextSibling {
			if alt := find(child); alt != "" {
				return alt
			}
		}
		return ""
	}
	return find(node)
}

func chandraExtractImageMetadata(pageImage image.Image, block chandraLayoutBlock, imageID, alt string) map[string]any {
	if pageImage == nil {
		return nil
	}
	sub, ok := pageImage.(interface {
		SubImage(r image.Rectangle) image.Image
	})
	if !ok {
		return nil
	}
	bounds := pageImage.Bounds()
	rect := normalizedBBoxToImageRect(block.BBox, bounds)
	if rect.Empty() {
		return nil
	}
	crop := sub.SubImage(rect)
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, crop, &jpeg.Options{Quality: 90}); err != nil {
		return nil
	}
	return map[string]any{
		"id":             imageID,
		"top_left_x":     rect.Min.X,
		"top_left_y":     rect.Min.Y,
		"bottom_right_x": rect.Max.X,
		"bottom_right_y": rect.Max.Y,
		"alt":            alt,
		"has_base64":     true,
		"image_base64":   "data:image/jpeg;base64," + base64.StdEncoding.EncodeToString(buf.Bytes()),
	}
}

func normalizedBBoxToImageRect(bbox [4]int, bounds image.Rectangle) image.Rectangle {
	width := bounds.Dx()
	height := bounds.Dy()
	x0 := bounds.Min.X + bbox[0]*width/defaultChandraBboxScale
	y0 := bounds.Min.Y + bbox[1]*height/defaultChandraBboxScale
	x1 := bounds.Min.X + bbox[2]*width/defaultChandraBboxScale
	y1 := bounds.Min.Y + bbox[3]*height/defaultChandraBboxScale
	rect := image.Rect(x0, y0, x1, y1).Intersect(bounds)
	if rect.Dx() <= 0 || rect.Dy() <= 0 {
		return image.Rectangle{}
	}
	return rect
}

func attrValue(node *nethtml.Node, key string) string {
	for _, attr := range node.Attr {
		if strings.EqualFold(attr.Key, key) {
			return attr.Val
		}
	}
	return ""
}

func textContent(node *nethtml.Node) string {
	if node == nil {
		return ""
	}
	if node.Type == nethtml.TextNode {
		return stdhtml.UnescapeString(node.Data)
	}
	var parts []string
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		parts = append(parts, textContent(child))
	}
	return strings.Join(strings.Fields(strings.Join(parts, " ")), " ")
}

func stripMarkdownEmphasis(text string) string {
	text = strings.TrimSpace(text)
	text = strings.Trim(text, "*_")
	return strings.TrimSpace(text)
}

func escapeMarkdownAlt(text string) string {
	replacer := strings.NewReplacer("[", `\[`, "]", `\]`, "\n", " ")
	return replacer.Replace(strings.Join(strings.Fields(text), " "))
}
