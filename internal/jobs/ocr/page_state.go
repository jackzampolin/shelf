package ocr

// PageState tracks the OCR state of a single page.
// This type is shared between the standalone ocr job and process_book.
type PageState struct {
	PageDocID string // DefraDB document ID for the Page record

	// Extraction state
	ExtractDone bool

	// OCR state per provider
	OcrResults map[string]string // provider -> OCR text
	OcrDone    map[string]bool   // provider -> completed
}

// NewPageState creates a new page state with initialized maps.
func NewPageState() *PageState {
	return &PageState{
		OcrResults: make(map[string]string),
		OcrDone:    make(map[string]bool),
	}
}

// AllOcrDone returns true if all providers have completed OCR for this page.
func (p *PageState) AllOcrDone(providers []string) bool {
	for _, provider := range providers {
		if !p.OcrDone[provider] {
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
		OcrDone:     make(map[string]bool),
	}
	for k, v := range p.OcrResults {
		clone.OcrResults[k] = v
	}
	for k, v := range p.OcrDone {
		clone.OcrDone[k] = v
	}
	return clone
}
