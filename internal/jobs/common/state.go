package common

import (
	"fmt"
	"sync"

	"github.com/jackzampolin/shelf/internal/home"
)

// HomeDir is an alias for home.Dir for external use.
type HomeDir = home.Dir

// PageState tracks the processing state of a single page.
// All fields are unexported and protected by an internal mutex for thread-safe access.
// Use the provided accessor methods to read/write state.
type PageState struct {
	mu sync.RWMutex

	// DefraDB document ID for the Page record
	pageDocID string

	// Extraction state
	extractDone bool

	// OCR state per provider.
	// Key presence indicates completion; value is the OCR text (may be empty for blank pages).
	ocrResults map[string]string // provider -> OCR text

	// Pipeline state (beyond OCR)
	blendDone   bool
	blendedText string // Cached blend result for label work unit
	labelDone   bool
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

// SetBlendResult sets the blend result and marks blend as done (thread-safe).
func (p *PageState) SetBlendResult(blendedText string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.blendedText = blendedText
	p.blendDone = true
}

// GetBlendedText returns the blended text (thread-safe).
func (p *PageState) GetBlendedText() string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.blendedText
}

// IsBlendDone returns true if blend is complete (thread-safe).
func (p *PageState) IsBlendDone() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.blendDone
}

// SetBlendDone marks blend as complete without updating blended text (thread-safe).
// Use this when loading state from DB where blend_complete is true but text isn't cached.
func (p *PageState) SetBlendDone(done bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.blendDone = done
}

// SetLabelDone marks label as complete (thread-safe).
func (p *PageState) SetLabelDone(done bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.labelDone = done
}

// IsLabelDone returns true if label is complete (thread-safe).
func (p *PageState) IsLabelDone() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.labelDone
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
// Fields are unexported; use the provided methods for all access.
type OperationState struct {
	status  OpStatus
	retries int
}

// NewOperationState creates an OperationState with given status and retries.
// Used for loading state from database.
func NewOperationState(status OpStatus, retries int) OperationState {
	return OperationState{status: status, retries: retries}
}

// Start marks the operation as in progress. Returns error if already started.
func (o *OperationState) Start() error {
	if o.status != OpNotStarted {
		return fmt.Errorf("operation already %s", o.status)
	}
	o.status = OpInProgress
	return nil
}

// Complete marks the operation as successfully completed.
func (o *OperationState) Complete() {
	o.status = OpComplete
}

// Fail records a failure and returns true if permanently failed (max retries reached).
func (o *OperationState) Fail(maxRetries int) bool {
	o.retries++
	if o.retries >= maxRetries {
		o.status = OpFailed
		return true
	}
	o.status = OpNotStarted // Allow retry
	return false
}

// Reset resets the operation to not started state (for rollback on persist failure).
func (o *OperationState) Reset() {
	o.status = OpNotStarted
}

// IsStarted returns true if the operation has been started.
func (o *OperationState) IsStarted() bool {
	return o.status == OpInProgress
}

// IsDone returns true if the operation is complete or permanently failed.
func (o *OperationState) IsDone() bool {
	return o.status == OpComplete || o.status == OpFailed
}

// IsFailed returns true if the operation permanently failed.
func (o *OperationState) IsFailed() bool {
	return o.status == OpFailed
}

// IsComplete returns true if the operation completed successfully.
func (o *OperationState) IsComplete() bool {
	return o.status == OpComplete
}

// CanStart returns true if the operation can be started (not started, not done).
func (o *OperationState) CanStart() bool {
	return o.status == OpNotStarted
}

// GetRetries returns the current retry count.
func (o *OperationState) GetRetries() int {
	return o.retries
}

// BookState tracks all state for a book: identity, context, pages, config, prompts, operations.
// This consolidates everything about a book so the Job struct can be thin.
//
// Thread-safety: Fields are categorized as:
//   - Immutable: Set during LoadBook, never modified. Safe to read without lock.
//   - Mutable: Modified during job execution. Use accessor methods for thread-safe access.
//
// Prefer using accessor methods for all field access.
type BookState struct {
	mu sync.RWMutex // Protects mutable fields

	// Identity (immutable after LoadBook)
	BookID    string
	BookDocID string

	// Context (immutable after LoadBook)
	HomeDir    *home.Dir
	PDFs       PDFList
	TotalPages int

	// Page state - use GetPage/GetOrCreatePage/ForEachPage methods
	Pages map[int]*PageState

	// Provider config (immutable after LoadBook)
	OcrProviders     []string
	BlendProvider    string
	LabelProvider    string
	MetadataProvider string
	TocProvider      string
	DebugAgents      bool // Enable debug logging for agent executions

	// Resolved prompts (immutable after LoadBook)
	Prompts    map[string]string // prompt_key -> resolved text
	PromptCIDs map[string]string // prompt_key -> CID for traceability

	// Book-level operation state (mutable - use accessor methods)
	Metadata   OperationState
	TocFinder  OperationState
	TocExtract OperationState

	// ToC finder results (mutable - use accessor methods)
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

// CountLabeledPages returns the number of pages that have completed labeling.
func (b *BookState) CountLabeledPages() int {
	count := 0
	b.ForEachPage(func(pageNum int, state *PageState) {
		if state.IsLabelDone() {
			count++
		}
	})
	return count
}

// AllPagesComplete returns true if all pages have completed the page-level pipeline.
func (b *BookState) AllPagesComplete() bool {
	allDone := true
	b.ForEachPage(func(pageNum int, state *PageState) {
		if !state.IsLabelDone() {
			allDone = false
		}
	})
	return allDone && b.CountPages() >= b.TotalPages
}

// ConsecutivePagesComplete returns true if pages 1 through `required` all have blend_complete.
// If TotalPages < required, checks up to TotalPages.
func (b *BookState) ConsecutivePagesComplete(required int) bool {
	if b.TotalPages < required {
		required = b.TotalPages
	}
	for pageNum := 1; pageNum <= required; pageNum++ {
		state := b.GetPage(pageNum)
		if state == nil || !state.IsBlendDone() {
			return false
		}
	}
	return true
}

// ProviderProgress contains progress data for a single provider.
type ProviderProgress struct {
	TotalExpected int
	Completed     int
}

// GetProviderProgress returns progress by provider for tracking job completion.
// Includes extract, OCR per provider, blend, and label progress.
func (b *BookState) GetProviderProgress() map[string]ProviderProgress {
	progress := make(map[string]ProviderProgress)

	// Track extraction progress
	extractCompleted := 0
	b.ForEachPage(func(pageNum int, state *PageState) {
		if state.IsExtractDone() {
			extractCompleted++
		}
	})
	progress["extract"] = ProviderProgress{
		TotalExpected: b.TotalPages,
		Completed:     extractCompleted,
	}

	// Track OCR progress per provider
	for _, provider := range b.OcrProviders {
		completed := 0
		b.ForEachPage(func(pageNum int, state *PageState) {
			if state.OcrComplete(provider) {
				completed++
			}
		})
		progress[provider] = ProviderProgress{
			TotalExpected: b.TotalPages,
			Completed:     completed,
		}
	}

	// Track blend progress
	blendCompleted := 0
	b.ForEachPage(func(pageNum int, state *PageState) {
		if state.IsBlendDone() {
			blendCompleted++
		}
	})
	progress["blend"] = ProviderProgress{
		TotalExpected: b.TotalPages,
		Completed:     blendCompleted,
	}

	// Track label progress
	labelCompleted := 0
	b.ForEachPage(func(pageNum int, state *PageState) {
		if state.IsLabelDone() {
			labelCompleted++
		}
	})
	progress["label"] = ProviderProgress{
		TotalExpected: b.TotalPages,
		Completed:     labelCompleted,
	}

	return progress
}

// --- Thread-safe accessors for mutable ToC fields ---

// GetTocFound returns whether a ToC was found (thread-safe).
func (b *BookState) GetTocFound() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.TocFound
}

// SetTocFound sets whether a ToC was found (thread-safe).
func (b *BookState) SetTocFound(found bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.TocFound = found
}

// GetTocPageRange returns the ToC page range (thread-safe).
// Returns (startPage, endPage).
func (b *BookState) GetTocPageRange() (int, int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.TocStartPage, b.TocEndPage
}

// SetTocPageRange sets the ToC page range (thread-safe).
func (b *BookState) SetTocPageRange(startPage, endPage int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.TocStartPage = startPage
	b.TocEndPage = endPage
}

// SetTocResult sets all ToC finder results atomically (thread-safe).
func (b *BookState) SetTocResult(found bool, startPage, endPage int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.TocFound = found
	b.TocStartPage = startPage
	b.TocEndPage = endPage
}

// --- Thread-safe accessors for Prompts ---

// GetPrompt returns the resolved prompt text for a key (thread-safe).
func (b *BookState) GetPrompt(key string) string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.Prompts[key]
}

// GetPromptCID returns the prompt CID for a key (thread-safe).
func (b *BookState) GetPromptCID(key string) string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.PromptCIDs[key]
}
