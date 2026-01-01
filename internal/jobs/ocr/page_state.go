package ocr

// PageState tracks the OCR state of a single page.
// This type is shared between the standalone ocr job and process_book.
type PageState struct {
	PageDocID string // DefraDB document ID for the Page record

	// Extraction state
	ExtractDone bool

	// OCR state per provider.
	// Key presence indicates completion; value is the OCR text (may be empty for blank pages).
	// Use OcrComplete() to check completion, MarkOcrComplete() to set.
	OcrResults map[string]string // provider -> OCR text
}

// NewPageState creates a new page state with initialized maps.
func NewPageState() *PageState {
	return &PageState{
		OcrResults: make(map[string]string),
	}
}

// OcrComplete returns true if OCR is complete for the given provider.
func (p *PageState) OcrComplete(provider string) bool {
	_, ok := p.OcrResults[provider]
	return ok
}

// MarkOcrComplete marks OCR as complete for a provider with the given result.
func (p *PageState) MarkOcrComplete(provider, text string) {
	p.OcrResults[provider] = text
}

// AllOcrDone returns true if all providers have completed OCR for this page.
func (p *PageState) AllOcrDone(providers []string) bool {
	for _, provider := range providers {
		if !p.OcrComplete(provider) {
			return false
		}
	}
	return true
}

// Clone creates a deep copy of the page state.
func (p *PageState) Clone() *PageState {
	clone := &PageState{
		PageDocID:   p.PageDocID,
		ExtractDone: p.ExtractDone,
		OcrResults:  make(map[string]string),
	}
	for k, v := range p.OcrResults {
		clone.OcrResults[k] = v
	}
	return clone
}
