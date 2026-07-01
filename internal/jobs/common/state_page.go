package common

import (
	"encoding/json"
	"log/slog"
	"sync"
)

var pageStateLogger = slog.Default().With("component", "page_state")

// PageState tracks the processing state of a single page.
// All fields are unexported and protected by an internal mutex for thread-safe access.
// Use the provided accessor methods to read/write state.
type PageState struct {
	mu sync.RWMutex

	// DefraDB document ID for the Page record
	pageDocID string
	pageCID   string // Latest commit CID for this page

	// Extraction state
	extractDone bool

	// OCR state per provider.
	// Key presence indicates completion; value is the OCR text (may be empty for blank pages).
	ocrResults map[string]string // provider -> OCR text

	// OCR markdown (stored directly from OCR, no blend step)
	ocrMarkdown string
	header      string
	footer      string

	// Cached data fields (populated on write-through or lazy load from DB)
	headings   []HeadingItem // Parsed headings from ocr_markdown
	dataLoaded bool          // True if ocr_markdown/headings loaded from DB
}

// NewPageState creates a new page state with initialized maps.
func NewPageState() *PageState {
	return &PageState{
		ocrResults: make(map[string]string),
	}
}

// OcrComplete returns true if OCR is complete for the given provider (thread-safe).
func (p *PageState) OcrComplete(provider string) bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	_, ok := p.ocrResults[provider]
	return ok
}

// MarkOcrComplete marks OCR as complete for a provider with the given result (thread-safe).
func (p *PageState) MarkOcrComplete(provider, text string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.ocrResults[provider] = text
}

// AllOcrDone returns true if all providers have completed OCR for this page (thread-safe).
func (p *PageState) AllOcrDone(providers []string) bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	for _, provider := range providers {
		if _, ok := p.ocrResults[provider]; !ok {
			return false
		}
	}
	return true
}

// SetExtractDone marks extraction as complete (thread-safe).
func (p *PageState) SetExtractDone(done bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.extractDone = done
}

// IsExtractDone returns true if extraction is complete (thread-safe).
func (p *PageState) IsExtractDone() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.extractDone
}

// SetOcrMarkdown sets the OCR markdown text (thread-safe).
func (p *PageState) SetOcrMarkdown(text string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.ocrMarkdown = text
}

// GetOcrMarkdown returns the OCR markdown text (thread-safe).
func (p *PageState) GetOcrMarkdown() string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.ocrMarkdown
}

// IsOcrMarkdownSet returns true if OCR markdown has been set (thread-safe).
func (p *PageState) IsOcrMarkdownSet() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.ocrMarkdown != ""
}

// GetOcrResult returns the OCR result for a provider (thread-safe).
func (p *PageState) GetOcrResult(provider string) (string, bool) {
	p.mu.RLock()
	defer p.mu.RUnlock()
	text, ok := p.ocrResults[provider]
	return text, ok
}

// GetPageDocID returns the page document ID (thread-safe).
func (p *PageState) GetPageDocID() string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.pageDocID
}

// SetPageDocID sets the page document ID (thread-safe).
func (p *PageState) SetPageDocID(docID string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.pageDocID = docID
}

// GetPageCID returns the page commit CID (thread-safe).
func (p *PageState) GetPageCID() string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.pageCID
}

// SetPageCID sets the page commit CID (thread-safe).
func (p *PageState) SetPageCID(cid string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.pageCID = cid
}

// --- Cache accessor methods ---

// GetHeadings returns the cached headings (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (p *PageState) GetHeadings() []HeadingItem {
	p.mu.RLock()
	defer p.mu.RUnlock()
	if p.headings == nil {
		return nil
	}
	result := make([]HeadingItem, len(p.headings))
	copy(result, p.headings)
	return result
}

// SetHeadings sets the cached headings (thread-safe).
func (p *PageState) SetHeadings(headings []HeadingItem) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.headings = headings
}

// IsDataLoaded returns true if page data has been loaded from DB (thread-safe).
func (p *PageState) IsDataLoaded() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.dataLoaded
}

// SetDataLoaded marks the page data as loaded from DB (thread-safe).
func (p *PageState) SetDataLoaded(loaded bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.dataLoaded = loaded
}

// SetOcrMarkdownWithHeadings sets the OCR markdown and headings together (thread-safe).
// Use this for write-through caching when persisting OCR results.
func (p *PageState) SetOcrMarkdownWithHeadings(text string, headings []HeadingItem) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.ocrMarkdown = text
	p.headings = headings
	p.dataLoaded = true
}

// GetHeader returns the OCR-detected running header (thread-safe).
func (p *PageState) GetHeader() string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.header
}

// SetHeader sets the OCR-detected running header (thread-safe).
func (p *PageState) SetHeader(header string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.header = header
}

// GetFooter returns the OCR-detected running footer (thread-safe).
func (p *PageState) GetFooter() string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.footer
}

// SetFooter sets the OCR-detected running footer (thread-safe).
func (p *PageState) SetFooter(footer string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.footer = footer
}

// PopulateFromDBResult populates cache fields from a DB query result map.
// This is used for lazy loading and batch preloading.
func (p *PageState) PopulateFromDBResult(data map[string]any) {
	p.mu.Lock()
	defer p.mu.Unlock()

	if om, ok := data["ocr_markdown"].(string); ok {
		p.ocrMarkdown = om
	}
	if header, ok := data["header"].(string); ok {
		p.header = header
	}
	if footer, ok := data["footer"].(string); ok {
		p.footer = footer
	}

	if h, ok := data["headings"].(string); ok && h != "" {
		var headings []HeadingItem
		if err := json.Unmarshal([]byte(h), &headings); err != nil {
			sample := h
			if len(sample) > 200 {
				sample = sample[:200] + "..."
			}
			pageStateLogger.Error("failed to parse headings JSON in PopulateFromDBResult",
				"error", err, "content_preview", sample)
		} else {
			p.headings = headings
		}
	}

	p.dataLoaded = true
}
