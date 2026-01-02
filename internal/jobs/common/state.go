package common

import (
	"fmt"
	"sync"

	"github.com/jackzampolin/shelf/internal/home"
)

// HomeDir is an alias for home.Dir for external use.
type HomeDir = home.Dir

// PageState tracks the processing state of a single page.
// All fields are protected by an internal mutex for thread-safe access.
type PageState struct {
	mu sync.RWMutex

	// DefraDB document ID for the Page record
	PageDocID string

	// Extraction state
	ExtractDone bool

	// OCR state per provider.
	// Key presence indicates completion; value is the OCR text (may be empty for blank pages).
	OcrResults map[string]string // provider -> OCR text

	// Pipeline state (beyond OCR)
	BlendDone   bool
	BlendedText string // Cached blend result for label work unit
	LabelDone   bool
}

// NewPageState creates a new page state with initialized maps.
func NewPageState() *PageState {
	return &PageState{
		OcrResults: make(map[string]string),
	}
}

// OcrComplete returns true if OCR is complete for the given provider (thread-safe).
func (p *PageState) OcrComplete(provider string) bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	_, ok := p.OcrResults[provider]
	return ok
}

// MarkOcrComplete marks OCR as complete for a provider with the given result (thread-safe).
func (p *PageState) MarkOcrComplete(provider, text string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.OcrResults[provider] = text
}

// AllOcrDone returns true if all providers have completed OCR for this page (thread-safe).
func (p *PageState) AllOcrDone(providers []string) bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	for _, provider := range providers {
		if _, ok := p.OcrResults[provider]; !ok {
			return false
		}
	}
	return true
}

// SetExtractDone marks extraction as complete (thread-safe).
func (p *PageState) SetExtractDone(done bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.ExtractDone = done
}

// IsExtractDone returns true if extraction is complete (thread-safe).
func (p *PageState) IsExtractDone() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.ExtractDone
}

// SetBlendResult sets the blend result and marks blend as done (thread-safe).
func (p *PageState) SetBlendResult(blendedText string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.BlendedText = blendedText
	p.BlendDone = true
}

// GetBlendedText returns the blended text (thread-safe).
func (p *PageState) GetBlendedText() string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.BlendedText
}

// IsBlendDone returns true if blend is complete (thread-safe).
func (p *PageState) IsBlendDone() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.BlendDone
}

// SetLabelDone marks label as complete (thread-safe).
func (p *PageState) SetLabelDone(done bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.LabelDone = done
}

// IsLabelDone returns true if label is complete (thread-safe).
func (p *PageState) IsLabelDone() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.LabelDone
}

// GetOcrResult returns the OCR result for a provider (thread-safe).
func (p *PageState) GetOcrResult(provider string) (string, bool) {
	p.mu.RLock()
	defer p.mu.RUnlock()
	text, ok := p.OcrResults[provider]
	return text, ok
}

// GetPageDocID returns the page document ID (thread-safe).
func (p *PageState) GetPageDocID() string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.PageDocID
}

// SetPageDocID sets the page document ID (thread-safe).
func (p *PageState) SetPageDocID(docID string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.PageDocID = docID
}

// OpStatus represents the status of a book-level operation.
type OpStatus int

const (
	OpNotStarted OpStatus = iota
	OpInProgress
	OpComplete
	OpFailed
)

// String returns the string representation of the status.
func (s OpStatus) String() string {
	switch s {
	case OpNotStarted:
		return "not_started"
	case OpInProgress:
		return "in_progress"
	case OpComplete:
		return "complete"
	case OpFailed:
		return "failed"
	default:
		return "unknown"
	}
}

// OperationState tracks the state of a retriable book-level operation.
type OperationState struct {
	Status  OpStatus
	Retries int
}

// Start marks the operation as in progress. Returns error if already started.
func (o *OperationState) Start() error {
	if o.Status != OpNotStarted {
		return fmt.Errorf("operation already %s", o.Status)
	}
	o.Status = OpInProgress
	return nil
}

// Complete marks the operation as successfully completed.
func (o *OperationState) Complete() {
	o.Status = OpComplete
}

// Fail records a failure and returns true if permanently failed (max retries reached).
func (o *OperationState) Fail(maxRetries int) bool {
	o.Retries++
	if o.Retries >= maxRetries {
		o.Status = OpFailed
		return true
	}
	o.Status = OpNotStarted // Allow retry
	return false
}

// IsStarted returns true if the operation has been started.
func (o *OperationState) IsStarted() bool {
	return o.Status == OpInProgress
}

// IsDone returns true if the operation is complete or permanently failed.
func (o *OperationState) IsDone() bool {
	return o.Status == OpComplete || o.Status == OpFailed
}

// IsFailed returns true if the operation permanently failed.
func (o *OperationState) IsFailed() bool {
	return o.Status == OpFailed
}

// IsComplete returns true if the operation completed successfully.
func (o *OperationState) IsComplete() bool {
	return o.Status == OpComplete
}

// CanStart returns true if the operation can be started (not started, not done).
func (o *OperationState) CanStart() bool {
	return o.Status == OpNotStarted
}

// BookState tracks all state for a book: identity, context, pages, config, prompts, operations.
// This consolidates everything about a book so the Job struct can be thin.
type BookState struct {
	mu sync.RWMutex // Thread-safe access

	// Identity
	BookID    string
	BookDocID string

	// Context
	HomeDir    *home.Dir
	PDFs       PDFList
	TotalPages int

	// Page state (loaded from DB, updated during job)
	Pages map[int]*PageState

	// Provider config (resolved at job start, can be per-book)
	OcrProviders     []string
	BlendProvider    string
	LabelProvider    string
	MetadataProvider string
	TocProvider      string
	DebugAgents      bool // Enable debug logging for agent executions

	// Resolved prompts (cached at job start, supports per-book overrides)
	Prompts    map[string]string // prompt_key -> resolved text
	PromptCIDs map[string]string // prompt_key -> CID for traceability

	// Book-level operation state
	Metadata   OperationState
	TocFinder  OperationState
	TocExtract OperationState

	// ToC finder results (set when TocFinder completes successfully)
	TocFound     bool
	TocStartPage int
	TocEndPage   int
}

// NewBookState creates a new BookState with initialized maps.
func NewBookState(bookID string) *BookState {
	return &BookState{
		BookID:     bookID,
		Pages:      make(map[int]*PageState),
		Prompts:    make(map[string]string),
		PromptCIDs: make(map[string]string),
	}
}

// GetPage returns the page state for a given page number (thread-safe).
func (b *BookState) GetPage(pageNum int) *PageState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.Pages[pageNum]
}

// GetOrCreatePage returns the page state for a page, creating it if needed (thread-safe).
func (b *BookState) GetOrCreatePage(pageNum int) *PageState {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.Pages[pageNum] == nil {
		b.Pages[pageNum] = NewPageState()
	}
	return b.Pages[pageNum]
}

// UpdatePage updates the page state for a page with a function (thread-safe).
func (b *BookState) UpdatePage(pageNum int, fn func(*PageState)) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.Pages[pageNum] == nil {
		b.Pages[pageNum] = NewPageState()
	}
	fn(b.Pages[pageNum])
}

// ForEachPage calls the function for each page (thread-safe, read lock).
func (b *BookState) ForEachPage(fn func(pageNum int, state *PageState)) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	for pageNum, state := range b.Pages {
		fn(pageNum, state)
	}
}

// CountPages returns the number of pages in the state.
func (b *BookState) CountPages() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.Pages)
}
