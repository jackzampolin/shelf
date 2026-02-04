package common

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/svcctx"
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
			slog.Error("failed to parse headings JSON in PopulateFromDBResult",
				"error", err, "content_preview", sample)
		} else {
			p.headings = headings
		}
	}

	p.dataLoaded = true
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

// BookMetadata contains extracted book metadata.
// Populated by metadata extraction or lazy-loaded from DefraDB.
type BookMetadata struct {
	Title           string   `json:"title,omitempty"`
	Author          string   `json:"author,omitempty"`
	Authors         []string `json:"authors,omitempty"`
	ISBN            string   `json:"isbn,omitempty"`
	LCCN            string   `json:"lccn,omitempty"`
	Publisher       string   `json:"publisher,omitempty"`
	PublicationYear int      `json:"publication_year,omitempty"`
	Language        string   `json:"language,omitempty"`
	Description     string   `json:"description,omitempty"`
	Subjects        []string `json:"subjects,omitempty"`
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

// Retries returns the current retry count (value receiver for convenience).
func (o OperationState) Retries() int {
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

	// Book metadata (mutable - populated by metadata extraction or lazy-loaded from DB)
	bookMetadata       *BookMetadata
	bookMetadataLoaded bool // True if metadata has been loaded/attempted

	// Version tracking (mutable - use accessor methods)
	bookCID       string
	tocCID        string
	operationCIDs map[OpType]string // CID when each operation completed
	cidIndex      map[string]map[string]string

	// Context (immutable after LoadBook)
	HomeDir    *home.Dir
	PDFs       PDFList
	TotalPages int

	// Page state - use GetPage/GetOrCreatePage/ForEachPage methods
	Pages map[int]*PageState

	// Provider config (immutable after LoadBook)
	OcrProviders     []string
	MetadataProvider string
	TocProvider      string
	DebugAgents      bool // Enable debug logging for agent executions

	// Pipeline stage toggles (immutable after LoadBook)
	// Used by variants to enable/disable stages
	EnableOCR         bool
	EnableMetadata    bool
	EnableTocFinder   bool
	EnableTocExtract  bool
	EnableTocLink     bool
	EnableTocFinalize bool
	EnableStructure   bool

	// Resolved prompts (immutable after LoadBook)
	Prompts    map[string]string // prompt_key -> resolved text
	PromptCIDs map[string]string // prompt_key -> CID for traceability

	// Generic operation state map (mutable - use Op* methods for access)
	ops map[OpType]*OperationState

	// ToC document ID (set during LoadBook, used for persistence)
	tocDocID string

	// Legacy operation state fields - delegated to ops map
	// These are kept as computed properties via the deprecated wrapper methods.
	// New code should use Op* methods and OpRegistry.

	// Structure phase tracking (mutable - unexported, use accessor methods)
	// Phases: build -> extract -> classify -> polish -> finalize
	structurePhase             string
	structureChaptersTotal     int
	structureChaptersExtracted int
	structureChaptersPolished  int
	structurePolishFailed      int

	// Structure sub-job state (mutable - unexported, use accessor methods)
	structureChapters           []*ChapterState
	structureClassifications    map[string]string // entry_id -> matter_type
	structureClassifyReasonings map[string]string // entry_id -> reasoning
	structureClassifyPending    bool

	// Finalize ToC sub-job state (mutable - unexported, use accessor methods)
	finalizePhase           string
	finalizePatternResult   *FinalizePatternResult
	finalizePagePatternCtx  *PagePatternContext // Body boundaries and chapter patterns for finalize
	entriesToFind           []*EntryToFind
	finalizeEntriesComplete int
	finalizeEntriesFound    int
	finalizeGaps            []*FinalizeGap
	finalizeGapsComplete    int
	finalizeGapsFixes       int

	// ToC finder results (mutable - unexported, use accessor methods)
	tocFound     bool
	tocStartPage int
	tocEndPage   int

	// ToC entries loaded from DB (unexported, use accessor methods)
	tocEntries []*toc_entry_finder.TocEntry

	// Linked ToC entries with page associations (unexported, use accessor methods)
	// Used by finalize_toc and common_structure phases
	linkedEntries []*LinkedTocEntry

	// ToC link progress counters (persisted to Book for crash recovery)
	tocLinkEntriesTotal int
	tocLinkEntriesDone  int

	// Body page range (set during finalize phase)
	bodyStart int
	bodyEnd   int

	// Agent states for job resume (mutable - unexported, use accessor methods)
	// Key format: "agent_type" for single agents, "agent_type:entry_doc_id" for per-entry agents
	agentStates map[string]*AgentState

	// Cost tracking (mutable - unexported, use accessor methods)
	// Write-through: updated when work units complete, lazy-loaded from DB on first access
	costsByStage map[string]float64 // stage -> accumulated cost USD
	totalCost    float64            // total accumulated cost USD
	costsLoaded  bool               // true if costs have been loaded from DB

	// Agent run logs (mutable - unexported, use accessor methods)
	// Write-through: updated when agent runs complete, lazy-loaded from DB on first access
	agentRuns       []AgentRunSummary // cached summaries of agent executions
	agentRunsLoaded bool              // true if agent runs have been loaded from DB

	// Store abstracts DB operations for testability.
	// When nil, functions fall back to extracting client/sink from context.
	Store StateStore
}

// NewBookState creates a new BookState with initialized maps.
func NewBookState(bookID string) *BookState {
	return &BookState{
		BookID:     bookID,
		BookDocID:  bookID, // Same as BookID - both are the DefraDB document ID
		Pages:      make(map[int]*PageState),
		Prompts:    make(map[string]string),
		PromptCIDs: make(map[string]string),
		ops: map[OpType]*OperationState{
			OpMetadata:    {},
			OpTocFinder:   {},
			OpTocExtract:  {},
			OpTocLink:     {},
			OpTocFinalize: {},
			OpStructure:   {},
		},
		operationCIDs:               make(map[OpType]string),
		cidIndex:                    make(map[string]map[string]string),
		agentStates:                 make(map[string]*AgentState),
		structureClassifications:    make(map[string]string),
		structureClassifyReasonings: make(map[string]string),
		costsByStage:                make(map[string]float64),
	}
}

// GetBookCID returns the latest book commit CID (thread-safe).
func (b *BookState) GetBookCID() string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.bookCID
}

// SetBookCID sets the latest book commit CID (thread-safe).
func (b *BookState) SetBookCID(cid string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.bookCID = cid
	b.trackCIDLocked("Book", b.BookID, cid)
}

// GetTocCID returns the latest ToC commit CID (thread-safe).
func (b *BookState) GetTocCID() string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocCID
}

// SetTocCID sets the latest ToC commit CID (thread-safe).
func (b *BookState) SetTocCID(cid string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocCID = cid
	if b.tocDocID != "" {
		b.trackCIDLocked("ToC", b.tocDocID, cid)
	}
}

// GetOperationCID returns the commit CID for a completed operation (thread-safe).
func (b *BookState) GetOperationCID(op OpType) string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.operationCIDs[op]
}

// SetOperationCID sets the commit CID for a completed operation (thread-safe).
func (b *BookState) SetOperationCID(op OpType, cid string) {
	if cid == "" {
		return
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.operationCIDs == nil {
		b.operationCIDs = make(map[OpType]string)
	}
	b.operationCIDs[op] = cid
}

// TrackWrite updates CID tracking for a write result.
func (b *BookState) TrackWrite(collection, docID, cid string) {
	if cid == "" || docID == "" {
		return
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	b.trackCIDLocked(collection, docID, cid)

	switch collection {
	case "Book":
		if docID == b.BookID {
			b.bookCID = cid
		}
	case "ToC":
		if docID == b.tocDocID {
			b.tocCID = cid
		}
	case "Page":
		for _, state := range b.Pages {
			if state != nil && state.GetPageDocID() == docID {
				state.SetPageCID(cid)
				break
			}
		}
	case "Chapter":
		for _, chapter := range b.structureChapters {
			if chapter != nil && chapter.DocID == docID {
				chapter.CID = cid
				break
			}
		}
	case "AgentState":
		for _, state := range b.agentStates {
			if state != nil && state.DocID == docID {
				state.CID = cid
				break
			}
		}
	}
}

// GetCID returns the tracked CID for a collection/docID pair.
func (b *BookState) GetCID(collection, docID string) string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.cidIndex == nil {
		return ""
	}
	if docs, ok := b.cidIndex[collection]; ok {
		return docs[docID]
	}
	return ""
}

// trackCIDLocked stores a CID in the index. Caller must hold b.mu.
func (b *BookState) trackCIDLocked(collection, docID, cid string) {
	if cid == "" || docID == "" {
		return
	}
	if b.cidIndex == nil {
		b.cidIndex = make(map[string]map[string]string)
	}
	if b.cidIndex[collection] == nil {
		b.cidIndex[collection] = make(map[string]string)
	}
	b.cidIndex[collection][docID] = cid
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

// GetPageAtCID loads a page's state at a specific DefraDB commit CID.
func (b *BookState) GetPageAtCID(ctx context.Context, pageNum int, cid string) (map[string]any, error) {
	if cid == "" {
		return nil, fmt.Errorf("cid is required")
	}
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query, vars := defra.NewQuery("Page").
		Filter("book_id", b.BookID).
		Filter("page_num", pageNum).
		WithCID(cid).
		Fields("_docID", "page_num", "ocr_markdown", "headings", "ocr_complete").
		Build()

	resp, err := defraClient.Execute(ctx, query, vars)
	if err != nil {
		return nil, err
	}
	pages, ok := resp.Data["Page"].([]any)
	if !ok || len(pages) == 0 {
		return nil, fmt.Errorf("page not found at CID %s", cid)
	}
	page, ok := pages[0].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("unexpected page format at CID %s", cid)
	}
	return page, nil
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

// CountOcrPages returns the number of pages that have OCR markdown set.
func (b *BookState) CountOcrPages() int {
	count := 0
	b.ForEachPage(func(pageNum int, state *PageState) {
		if state.IsOcrMarkdownSet() {
			count++
		}
	})
	return count
}

// AllPagesComplete returns true if all pages have completed the page-level pipeline (OCR).
func (b *BookState) AllPagesComplete() bool {
	allDone := true
	b.ForEachPage(func(pageNum int, state *PageState) {
		if !state.AllOcrDone(b.OcrProviders) {
			allDone = false
		}
	})
	return allDone && b.CountPages() >= b.TotalPages
}

// AllPagesOcrComplete returns true if all pages have completed OCR.
func (b *BookState) AllPagesOcrComplete() bool {
	allDone := true
	b.ForEachPage(func(pageNum int, state *PageState) {
		if !state.AllOcrDone(b.OcrProviders) {
			allDone = false
		}
	})
	return allDone && b.CountPages() >= b.TotalPages
}

// ConsecutivePagesComplete returns true if pages 1 through `required` all have OCR complete.
// If TotalPages < required, checks up to TotalPages.
func (b *BookState) ConsecutivePagesComplete(required int) bool {
	if b.TotalPages < required {
		required = b.TotalPages
	}
	for pageNum := 1; pageNum <= required; pageNum++ {
		state := b.GetPage(pageNum)
		if state == nil || !state.AllOcrDone(b.OcrProviders) {
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
// Includes extract and OCR per provider progress.
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

	return progress
}

// --- Thread-safe accessors for mutable ToC fields ---

// GetTocFound returns whether a ToC was found (thread-safe).
func (b *BookState) GetTocFound() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFound
}

// SetTocFound sets whether a ToC was found (thread-safe).
func (b *BookState) SetTocFound(found bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocFound = found
}

// GetTocPageRange returns the ToC page range (thread-safe).
// Returns (startPage, endPage).
func (b *BookState) GetTocPageRange() (int, int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocStartPage, b.tocEndPage
}

// SetTocPageRange sets the ToC page range (thread-safe).
func (b *BookState) SetTocPageRange(startPage, endPage int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocStartPage = startPage
	b.tocEndPage = endPage
}

// SetTocResult sets all ToC finder results atomically (thread-safe).
func (b *BookState) SetTocResult(found bool, startPage, endPage int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocFound = found
	b.tocStartPage = startPage
	b.tocEndPage = endPage
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

// --- Thread-safe accessors for TocEntries ---

// GetTocEntries returns the ToC entries (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetTocEntries() []*toc_entry_finder.TocEntry {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.tocEntries == nil {
		return nil
	}
	result := make([]*toc_entry_finder.TocEntry, len(b.tocEntries))
	copy(result, b.tocEntries)
	return result
}

// SetTocEntries sets the ToC entries (thread-safe).
func (b *BookState) SetTocEntries(entries []*toc_entry_finder.TocEntry) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocEntries = entries
}

// GetUnlinkedTocEntries returns only entries without actual_page linked.
// This filters the cached entries rather than re-querying DB.
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetUnlinkedTocEntries() []*toc_entry_finder.TocEntry {
	b.mu.RLock()
	defer b.mu.RUnlock()
	// TocEntries are already filtered to unlinked during load
	if b.tocEntries == nil {
		return nil
	}
	result := make([]*toc_entry_finder.TocEntry, len(b.tocEntries))
	copy(result, b.tocEntries)
	return result
}

// --- Thread-safe accessors for LinkedEntries ---

// GetLinkedEntries returns the linked ToC entries (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetLinkedEntries() []*LinkedTocEntry {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.linkedEntries == nil {
		return nil
	}
	result := make([]*LinkedTocEntry, len(b.linkedEntries))
	copy(result, b.linkedEntries)
	return result
}

// SetLinkedEntries sets the linked ToC entries (thread-safe).
func (b *BookState) SetLinkedEntries(entries []*LinkedTocEntry) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.linkedEntries = entries
}

// HasLinkedEntries returns true if linked entries are cached (thread-safe).
func (b *BookState) HasLinkedEntries() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.linkedEntries != nil
}

// SetStructurePhase sets the current structure processing phase (thread-safe).
func (b *BookState) SetStructurePhase(phase string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structurePhase = phase
}

// GetStructurePhase gets the current structure processing phase (thread-safe).
func (b *BookState) GetStructurePhase() string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structurePhase
}

// SetStructureProgress sets the structure progress counters (thread-safe).
func (b *BookState) SetStructureProgress(total, extracted, polished, failed int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureChaptersTotal = total
	b.structureChaptersExtracted = extracted
	b.structureChaptersPolished = polished
	b.structurePolishFailed = failed
}

// GetStructureProgress gets the structure progress counters (thread-safe).
func (b *BookState) GetStructureProgress() (total, extracted, polished, failed int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structureChaptersTotal, b.structureChaptersExtracted, b.structureChaptersPolished, b.structurePolishFailed
}

// IncrementStructurePolished increments the polished counter (thread-safe).
func (b *BookState) IncrementStructurePolished() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureChaptersPolished++
}

// IncrementStructurePolishFailed increments the polish failed counter (thread-safe).
func (b *BookState) IncrementStructurePolishFailed() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structurePolishFailed++
}

// --- Agent State Management ---

// AgentState tracks the state of an in-flight or completed agent for job resume.
// This allows agents to be restored from their conversation history after a crash.
type AgentState struct {
	// Identity
	AgentID   string // UUID for this agent instance
	AgentType string // "toc_finder", "toc_entry_finder", "chapter_finder", "gap_investigator"

	// Context - for multi-instance agents (like LinkToc entry agents)
	EntryDocID string // Which ToC entry this agent is for (if applicable)

	// Execution state
	Iteration int  // Current iteration number
	Complete  bool // Is agent done?

	// Conversation history (for resume) - JSON serialized
	MessagesJSON string // Serialized []providers.Message

	// In-flight tool call state (for resume mid-tool-execution) - JSON serialized
	PendingToolCalls string // Serialized []providers.ToolCall
	ToolResults      string // Serialized map[string]string (tool_call_id -> result)

	// Result (when complete) - JSON serialized
	ResultJSON string // Serialized agent.Result

	// Database identity
	DocID string // DefraDB document ID for this agent state
	CID   string // DefraDB commit CID for this agent state
}

// Valid agent types - used for validation
const (
	AgentTypeTocFinder       = "toc_finder"
	AgentTypeTocEntryFinder  = "toc_entry_finder"
	AgentTypeChapterFinder   = "chapter_finder"
	AgentTypeGapInvestigator = "gap_investigator"
)

// validAgentTypes is the set of valid agent type values.
var validAgentTypes = map[string]bool{
	AgentTypeTocFinder:       true,
	AgentTypeTocEntryFinder:  true,
	AgentTypeChapterFinder:   true,
	AgentTypeGapInvestigator: true,
}

// IsValidAgentType returns true if the agent type is valid.
func IsValidAgentType(agentType string) bool {
	return validAgentTypes[agentType]
}

// NewAgentState creates a new AgentState with validation.
// Returns an error if agentType is invalid or agentID is empty.
func NewAgentState(agentType, agentID string) (*AgentState, error) {
	if !IsValidAgentType(agentType) {
		return nil, fmt.Errorf("invalid agent type: %q (valid: %v)", agentType, []string{
			AgentTypeTocFinder, AgentTypeTocEntryFinder, AgentTypeChapterFinder, AgentTypeGapInvestigator,
		})
	}
	if agentID == "" {
		return nil, fmt.Errorf("agent_id is required")
	}
	return &AgentState{
		AgentType: agentType,
		AgentID:   agentID,
	}, nil
}

// AgentStateKey generates the map key for an agent state.
// Single agents use just their type, per-entry agents include entry doc ID.
func AgentStateKey(agentType string, entryDocID string) string {
	if entryDocID == "" {
		return agentType
	}
	return agentType + ":" + entryDocID
}

// GetAgentState returns the agent state for a given type and optional entry (thread-safe).
func (b *BookState) GetAgentState(agentType string, entryDocID string) *AgentState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	key := AgentStateKey(agentType, entryDocID)
	return b.agentStates[key]
}

// SetAgentState stores agent state (thread-safe).
func (b *BookState) SetAgentState(state *AgentState) {
	b.mu.Lock()
	defer b.mu.Unlock()
	key := AgentStateKey(state.AgentType, state.EntryDocID)
	b.agentStates[key] = state
	if state != nil {
		b.trackCIDLocked("AgentState", state.DocID, state.CID)
	}
}

// RemoveAgentState removes agent state (thread-safe).
func (b *BookState) RemoveAgentState(agentType string, entryDocID string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	key := AgentStateKey(agentType, entryDocID)
	delete(b.agentStates, key)
}

// GetAllAgentStates returns all agent states (thread-safe, returns a copy of keys).
func (b *BookState) GetAllAgentStates() []*AgentState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	states := make([]*AgentState, 0, len(b.agentStates))
	for _, state := range b.agentStates {
		states = append(states, state)
	}
	return states
}

// ClearAgentStates removes all agent states for a given type (thread-safe).
// Use this when resetting an operation to clear associated agent state.
func (b *BookState) ClearAgentStates(agentType string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for key := range b.agentStates {
		// Match exact type or type:suffix for per-entry agents
		if key == agentType || strings.HasPrefix(key, agentType+":") {
			delete(b.agentStates, key)
		}
	}
}

// --- Agent Run Summary (for caching executed agent logs) ---

// AgentRunSummary is a lightweight summary of an agent execution.
// Used for caching agent run history on BookState.
type AgentRunSummary struct {
	DocID       string // DefraDB document ID
	AgentType   string // Agent type (toc_finder, chapter_finder, etc.)
	JobID       string // Job that spawned this agent
	StartedAt   string // ISO timestamp
	CompletedAt string // ISO timestamp (empty if still running)
	Iterations  int    // Number of agent iterations
	Success     bool   // Whether the agent succeeded
	Error       string // Error message if failed
}

// --- Finalize ToC State Types ---

// FinalizePatternResult holds the results of ToC pattern analysis.
type FinalizePatternResult struct {
	Patterns  []DiscoveredPattern `json:"patterns"`
	Excluded  []ExcludedRange     `json:"excluded_ranges"`
	Reasoning string              `json:"reasoning"`
}

// DiscoveredPattern represents a chapter sequence to discover.
type DiscoveredPattern struct {
	PatternType   string `json:"pattern_type"`   // "sequential" or "named"
	LevelName     string `json:"level_name"`     // "chapter", "part", "section"
	HeadingFormat string `json:"heading_format"` // "Chapter {n}", "{n}", "CHAPTER {n}"
	RangeStart    string `json:"range_start"`    // "1", "I", "A"
	RangeEnd      string `json:"range_end"`      // "38", "X", "F"
	Level         int    `json:"level"`          // Structural depth: 1=part, 2=chapter, 3=section
	Reasoning     string `json:"reasoning"`
}

// ExcludedRange represents a page range to skip during discovery.
type ExcludedRange struct {
	StartPage int    `json:"start_page"`
	EndPage   int    `json:"end_page"`
	Reason    string `json:"reason"` // "back_matter", "front_matter", "bibliography", etc.
}

// EntryToFind represents a missing chapter/section to discover.
type EntryToFind struct {
	Key              string `json:"key"`            // Unique key like "chapter_14"
	LevelName        string `json:"level_name"`     // "chapter", "part"
	Identifier       string `json:"identifier"`     // "14", "III", "A"
	HeadingFormat    string `json:"heading_format"` // "Chapter {n}"
	Level            int    `json:"level"`
	ExpectedNearPage int    `json:"expected_near_page"` // Estimated page based on sequence
	SearchRangeStart int    `json:"search_range_start"`
	SearchRangeEnd   int    `json:"search_range_end"`
}

// FinalizeGap represents a gap in page coverage between entries.
type FinalizeGap struct {
	Key            string `json:"key"` // Unique key like "gap_100_150"
	StartPage      int    `json:"start_page"`
	EndPage        int    `json:"end_page"`
	Size           int    `json:"size"`
	PrevEntryTitle string `json:"prev_entry_title"`
	PrevEntryPage  int    `json:"prev_entry_page"`
	NextEntryTitle string `json:"next_entry_title"`
	NextEntryPage  int    `json:"next_entry_page"`
}

// --- Finalize State Accessors ---

// FinalizeState holds finalize ToC sub-job state within BookState.
type FinalizeState struct {
	Phase           string                 `json:"phase"` // pattern, discover, validate
	PatternResult   *FinalizePatternResult `json:"pattern_result"`
	EntriesToFind   []*EntryToFind         `json:"entries_to_find"`
	EntriesComplete int                    `json:"entries_complete"`
	EntriesFound    int                    `json:"entries_found"`
	Gaps            []*FinalizeGap         `json:"gaps"`
	GapsComplete    int                    `json:"gaps_complete"`
	GapsFixes       int                    `json:"gaps_fixes"`
}

// GetFinalizePhase returns the current finalize phase (thread-safe).
func (b *BookState) GetFinalizePhase() string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.finalizePhase
}

// SetFinalizePhase sets the current finalize phase (thread-safe).
func (b *BookState) SetFinalizePhase(phase string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizePhase = phase
}

// GetFinalizePatternResult returns the finalize pattern result (thread-safe).
func (b *BookState) GetFinalizePatternResult() *FinalizePatternResult {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.finalizePatternResult
}

// SetFinalizePatternResult sets the finalize pattern result (thread-safe).
func (b *BookState) SetFinalizePatternResult(result *FinalizePatternResult) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizePatternResult = result
}

// GetEntriesToFind returns entries to find in discover phase (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetEntriesToFind() []*EntryToFind {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.entriesToFind == nil {
		return nil
	}
	result := make([]*EntryToFind, len(b.entriesToFind))
	copy(result, b.entriesToFind)
	return result
}

// SetEntriesToFind sets entries to find in discover phase (thread-safe).
func (b *BookState) SetEntriesToFind(entries []*EntryToFind) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.entriesToFind = entries
}

// AppendEntryToFind adds an entry to find (thread-safe).
func (b *BookState) AppendEntryToFind(entry *EntryToFind) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.entriesToFind = append(b.entriesToFind, entry)
}

// GetEntriesToFindCount returns the number of entries to find (thread-safe).
func (b *BookState) GetEntriesToFindCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.entriesToFind)
}

// GetFinalizeGaps returns gaps to investigate (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetFinalizeGaps() []*FinalizeGap {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.finalizeGaps == nil {
		return nil
	}
	result := make([]*FinalizeGap, len(b.finalizeGaps))
	copy(result, b.finalizeGaps)
	return result
}

// SetFinalizeGaps sets gaps to investigate (thread-safe).
func (b *BookState) SetFinalizeGaps(gaps []*FinalizeGap) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeGaps = gaps
}

// AppendFinalizeGap adds a gap to investigate (thread-safe).
func (b *BookState) AppendFinalizeGap(gap *FinalizeGap) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeGaps = append(b.finalizeGaps, gap)
}

// GetFinalizeGapsCount returns the number of gaps to investigate (thread-safe).
func (b *BookState) GetFinalizeGapsCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.finalizeGaps)
}

// GetFinalizeProgress returns finalize progress counters (thread-safe).
func (b *BookState) GetFinalizeProgress() (entriesComplete, entriesFound, gapsComplete, gapsFixes int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.finalizeEntriesComplete, b.finalizeEntriesFound, b.finalizeGapsComplete, b.finalizeGapsFixes
}

// SetFinalizeProgress sets finalize progress counters (thread-safe).
func (b *BookState) SetFinalizeProgress(entriesComplete, entriesFound, gapsComplete, gapsFixes int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeEntriesComplete = entriesComplete
	b.finalizeEntriesFound = entriesFound
	b.finalizeGapsComplete = gapsComplete
	b.finalizeGapsFixes = gapsFixes
}

// --- ToC Link Progress ---

// GetTocLinkProgress returns toc link progress counters (thread-safe).
func (b *BookState) GetTocLinkProgress() (total, done int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocLinkEntriesTotal, b.tocLinkEntriesDone
}

// SetTocLinkProgress sets toc link progress counters (thread-safe).
func (b *BookState) SetTocLinkProgress(total, done int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocLinkEntriesTotal = total
	b.tocLinkEntriesDone = done
}

// IncrementTocLinkEntriesDone increments entries done (thread-safe).
func (b *BookState) IncrementTocLinkEntriesDone() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocLinkEntriesDone++
}

// IncrementFinalizeEntriesComplete increments entries complete (thread-safe).
func (b *BookState) IncrementFinalizeEntriesComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeEntriesComplete++
}

// IncrementFinalizeEntriesFound increments entries found (thread-safe).
func (b *BookState) IncrementFinalizeEntriesFound() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeEntriesFound++
}

// IncrementFinalizeGapsComplete increments gaps complete (thread-safe).
func (b *BookState) IncrementFinalizeGapsComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeGapsComplete++
}

// IncrementFinalizeGapsFixes increments gaps fixed (thread-safe).
func (b *BookState) IncrementFinalizeGapsFixes() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeGapsFixes++
}

// --- Structure State Types ---

// ChapterState tracks chapter during structure processing.
type ChapterState struct {
	// Identity
	EntryID   string `json:"entry_id"`   // Unique within book (e.g., "ch_001")
	UniqueKey string `json:"unique_key"` // For upsert: "{book_id}:{toc_entry_id}" or "{book_id}:orphan:{sort_order}"
	DocID     string `json:"doc_id"`     // DefraDB doc ID (after create)
	CID       string `json:"cid"`        // DefraDB commit CID (latest)

	// From ToC
	Title       string `json:"title"`
	Level       int    `json:"level"`
	LevelName   string `json:"level_name"`
	EntryNumber string `json:"entry_number"`
	SortOrder   int    `json:"sort_order"`
	Source      string `json:"source"`       // "toc", "heading", "reconciled"
	TocEntryID  string `json:"toc_entry_id"` // Link back to original TocEntry

	// Page boundaries
	StartPage int `json:"start_page"`
	EndPage   int `json:"end_page"`

	// Hierarchy
	ParentID string `json:"parent_id"` // entry_id of parent chapter

	// Matter classification (set in classify phase)
	MatterType        string `json:"matter_type"`        // "front_matter", "body", "back_matter"
	ClassifyReasoning string `json:"classify_reasoning"` // Why this classification was chosen

	// Content classification (granular, set in classify phase)
	ContentType           string `json:"content_type"`            // "preface", "body", "appendix", etc.
	AudioInclude          bool   `json:"audio_include"`           // Include in audiobook output
	AudioIncludeReasoning string `json:"audio_include_reasoning"` // Why include/exclude

	// Text content (set in extract phase)
	MechanicalText string `json:"mechanical_text,omitempty"`
	PageBreaks     []int  `json:"page_breaks,omitempty"`

	// Polished text (set in polish phase)
	PolishedText string `json:"polished_text,omitempty"`
	WordCount    int    `json:"word_count"`

	// Processing state
	ExtractDone  bool `json:"extract_done"`
	PolishDone   bool `json:"polish_done"`
	PolishFailed bool `json:"polish_failed"` // True if polish failed and fell back to mechanical text
}

// Copy returns a deep copy of the ChapterState.
func (c *ChapterState) Copy() *ChapterState {
	if c == nil {
		return nil
	}
	copy := *c // Shallow copy of all value fields
	// Deep copy the slice
	if c.PageBreaks != nil {
		copy.PageBreaks = make([]int, len(c.PageBreaks))
		for i, v := range c.PageBreaks {
			copy.PageBreaks[i] = v
		}
	}
	return &copy
}

// NewChapterState creates a new ChapterState with validation.
// Returns an error if required fields are missing or invalid.
func NewChapterState(entryID, uniqueKey, title string, startPage int) (*ChapterState, error) {
	if entryID == "" {
		return nil, fmt.Errorf("entry_id is required")
	}
	if uniqueKey == "" {
		return nil, fmt.Errorf("unique_key is required")
	}
	if title == "" {
		return nil, fmt.Errorf("title is required")
	}
	if startPage < 1 {
		return nil, fmt.Errorf("start_page must be >= 1, got %d", startPage)
	}
	return &ChapterState{
		EntryID:   entryID,
		UniqueKey: uniqueKey,
		Title:     title,
		StartPage: startPage,
	}, nil
}

// StructureState holds structure sub-job state within BookState (for serialization).
type StructureState struct {
	Phase              string            `json:"phase"` // build, extract, classify, polish, finalize
	Chapters           []*ChapterState   `json:"chapters"`
	ChaptersToExtract  int               `json:"chapters_to_extract"`
	ChaptersExtracted  int               `json:"chapters_extracted"`
	ExtractsFailed     int               `json:"extracts_failed"`
	ClassifyPending    bool              `json:"classify_pending"`
	Classifications    map[string]string `json:"classifications"`     // entry_id -> matter_type
	ClassifyReasonings map[string]string `json:"classify_reasonings"` // entry_id -> reasoning
	ChaptersToPolish   int               `json:"chapters_to_polish"`
	ChaptersPolished   int               `json:"chapters_polished"`
	PolishFailed       int               `json:"polish_failed"`
}

// GetStructureChapters returns deep copies of all structure chapters.
// Modifications to returned chapters do not affect BookState.
// Use UpdateChapter() to save changes back.
func (b *BookState) GetStructureChapters() []*ChapterState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.structureChapters == nil {
		return nil
	}
	result := make([]*ChapterState, len(b.structureChapters))
	for i, ch := range b.structureChapters {
		result[i] = ch.Copy()
	}
	return result
}

// SetStructureChapters sets the structure chapters (thread-safe).
func (b *BookState) SetStructureChapters(chapters []*ChapterState) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureChapters = chapters
	for _, chapter := range chapters {
		if chapter == nil {
			continue
		}
		b.trackCIDLocked("Chapter", chapter.DocID, chapter.CID)
	}
}

// GetStructureClassifications returns the matter classifications (thread-safe).
// Returns a copy of the map to prevent external modification.
func (b *BookState) GetStructureClassifications() map[string]string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.structureClassifications == nil {
		return nil
	}
	result := make(map[string]string, len(b.structureClassifications))
	for k, v := range b.structureClassifications {
		result[k] = v
	}
	return result
}

// SetStructureClassifications sets the matter classifications (thread-safe).
func (b *BookState) SetStructureClassifications(classifications map[string]string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureClassifications = classifications
}

// GetStructureClassifyPending returns whether classification is pending (thread-safe).
func (b *BookState) GetStructureClassifyPending() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structureClassifyPending
}

// SetStructureClassifyPending sets whether classification is pending (thread-safe).
func (b *BookState) SetStructureClassifyPending(pending bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureClassifyPending = pending
}

// GetChapterByEntryID returns a copy of the chapter by its entry ID.
// Returns nil if not found. Callers should modify the copy and then call
// UpdateChapter() to save changes back to BookState.
func (b *BookState) GetChapterByEntryID(entryID string) *ChapterState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	for _, ch := range b.structureChapters {
		if ch.EntryID == entryID {
			return ch.Copy()
		}
	}
	return nil
}

// UpdateChapter updates a chapter in the list (thread-safe).
func (b *BookState) UpdateChapter(chapter *ChapterState) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for i, ch := range b.structureChapters {
		if ch.EntryID == chapter.EntryID {
			b.structureChapters[i] = chapter
			return
		}
	}
}

// --- Page Pattern Context ---

// PagePatternContext holds page pattern analysis data for enhanced ToC finalization.
// This is populated from PagePatternResult during finalize phase.
type PagePatternContext struct {
	BodyStartPage   int
	BodyEndPage     int
	HasBoundaries   bool
	ChapterPatterns []DetectedChapter
}

// DetectedChapter represents a chapter detected by pattern analysis.
type DetectedChapter struct {
	PageNum       int
	RunningHeader string
	ChapterTitle  string
	ChapterNumber string
	Source        string // "pattern_analysis", "label", etc.
	Confidence    string // "high", "medium", "low"
}

// GetFinalizePagePatternCtx returns the page pattern context for finalize phase (thread-safe).
func (b *BookState) GetFinalizePagePatternCtx() *PagePatternContext {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.finalizePagePatternCtx
}

// SetFinalizePagePatternCtx sets the page pattern context for finalize phase (thread-safe).
func (b *BookState) SetFinalizePagePatternCtx(ctx *PagePatternContext) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizePagePatternCtx = ctx
}

// --- Structure Classification Reasonings ---

// GetStructureClassifyReasonings returns the classification reasonings map (thread-safe).
// Returns a copy of the map to prevent external modification.
func (b *BookState) GetStructureClassifyReasonings() map[string]string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.structureClassifyReasonings == nil {
		return nil
	}
	result := make(map[string]string, len(b.structureClassifyReasonings))
	for k, v := range b.structureClassifyReasonings {
		result[k] = v
	}
	return result
}

// SetStructureClassifyReasonings sets the classification reasonings map (thread-safe).
func (b *BookState) SetStructureClassifyReasonings(reasonings map[string]string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureClassifyReasonings = reasonings
}

// --- Body Page Range Accessors ---

// GetBodyRange returns the body page range (thread-safe).
func (b *BookState) GetBodyRange() (start, end int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.bodyStart, b.bodyEnd
}

// SetBodyRange sets the body page range (thread-safe).
func (b *BookState) SetBodyRange(start, end int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.bodyStart = start
	b.bodyEnd = end
}

// GetBodyStart returns the body start page (thread-safe).
func (b *BookState) GetBodyStart() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.bodyStart
}

// GetBodyEnd returns the body end page (thread-safe).
func (b *BookState) GetBodyEnd() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.bodyEnd
}

// --- Operation State Accessors ---
// Deprecated: These wrapper methods delegate to the generic Op* methods.
// New code should use OpStart(OpMetadata), OpComplete(OpMetadata), etc.

func (b *BookState) MetadataStart() error             { return b.OpStart(OpMetadata) }
func (b *BookState) MetadataComplete()                { b.OpComplete(OpMetadata) }
func (b *BookState) MetadataFail(maxRetries int) bool { return b.OpFail(OpMetadata, maxRetries) }
func (b *BookState) MetadataReset()                   { b.OpReset(OpMetadata) }
func (b *BookState) MetadataIsStarted() bool          { return b.OpIsStarted(OpMetadata) }
func (b *BookState) MetadataIsDone() bool             { return b.OpIsDone(OpMetadata) }
func (b *BookState) MetadataCanStart() bool           { return b.OpCanStart(OpMetadata) }
func (b *BookState) MetadataIsComplete() bool         { return b.OpIsComplete(OpMetadata) }
func (b *BookState) GetMetadataState() OperationState { return b.OpGetState(OpMetadata) }

// GetBookMetadata returns the book metadata (thread-safe).
// Returns nil if metadata has not been extracted or loaded.
// Use GetBookMetadataWithLazyLoad for lazy loading from DB.
func (b *BookState) GetBookMetadata() *BookMetadata {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.bookMetadata
}

// SetBookMetadata sets the book metadata (thread-safe).
// Called after metadata extraction completes.
func (b *BookState) SetBookMetadata(metadata *BookMetadata) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.bookMetadata = metadata
	b.bookMetadataLoaded = true
}

// GetBookMetadataWithLazyLoad returns book metadata, loading from DB if needed (thread-safe).
// Requires context with DefraClient for DB queries.
// Returns nil if metadata is not available in DB.
func (b *BookState) GetBookMetadataWithLazyLoad(ctx context.Context) *BookMetadata {
	b.mu.RLock()
	if b.bookMetadataLoaded {
		meta := b.bookMetadata
		b.mu.RUnlock()
		return meta
	}
	b.mu.RUnlock()

	// Need to load from DB - upgrade to write lock
	b.mu.Lock()
	defer b.mu.Unlock()

	// Double-check after acquiring write lock
	if b.bookMetadataLoaded {
		return b.bookMetadata
	}

	// Load from DefraDB
	metadata, loaded := loadBookMetadataFromDB(ctx, b.BookID)
	if loaded {
		b.bookMetadata = metadata
		b.bookMetadataLoaded = true
	}
	return b.bookMetadata
}

// GetBookTitle returns the book title (thread-safe convenience accessor).
func (b *BookState) GetBookTitle() string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.bookMetadata != nil {
		return b.bookMetadata.Title
	}
	return ""
}

func (b *BookState) TocFinderStart() error             { return b.OpStart(OpTocFinder) }
func (b *BookState) TocFinderComplete()                { b.OpComplete(OpTocFinder) }
func (b *BookState) TocFinderFail(maxRetries int) bool { return b.OpFail(OpTocFinder, maxRetries) }
func (b *BookState) TocFinderReset()                   { b.OpReset(OpTocFinder) }
func (b *BookState) TocFinderIsStarted() bool          { return b.OpIsStarted(OpTocFinder) }
func (b *BookState) TocFinderIsDone() bool             { return b.OpIsDone(OpTocFinder) }
func (b *BookState) TocFinderCanStart() bool           { return b.OpCanStart(OpTocFinder) }
func (b *BookState) TocFinderIsComplete() bool         { return b.OpIsComplete(OpTocFinder) }
func (b *BookState) GetTocFinderState() OperationState { return b.OpGetState(OpTocFinder) }

func (b *BookState) TocExtractStart() error             { return b.OpStart(OpTocExtract) }
func (b *BookState) TocExtractComplete()                { b.OpComplete(OpTocExtract) }
func (b *BookState) TocExtractFail(maxRetries int) bool { return b.OpFail(OpTocExtract, maxRetries) }
func (b *BookState) TocExtractReset()                   { b.OpReset(OpTocExtract) }
func (b *BookState) TocExtractIsStarted() bool          { return b.OpIsStarted(OpTocExtract) }
func (b *BookState) TocExtractIsDone() bool             { return b.OpIsDone(OpTocExtract) }
func (b *BookState) TocExtractCanStart() bool           { return b.OpCanStart(OpTocExtract) }
func (b *BookState) TocExtractIsComplete() bool         { return b.OpIsComplete(OpTocExtract) }
func (b *BookState) GetTocExtractState() OperationState { return b.OpGetState(OpTocExtract) }

func (b *BookState) TocLinkStart() error             { return b.OpStart(OpTocLink) }
func (b *BookState) TocLinkComplete()                { b.OpComplete(OpTocLink) }
func (b *BookState) TocLinkFail(maxRetries int) bool { return b.OpFail(OpTocLink, maxRetries) }
func (b *BookState) TocLinkReset()                   { b.OpReset(OpTocLink) }
func (b *BookState) TocLinkIsStarted() bool          { return b.OpIsStarted(OpTocLink) }
func (b *BookState) TocLinkIsDone() bool             { return b.OpIsDone(OpTocLink) }
func (b *BookState) TocLinkCanStart() bool           { return b.OpCanStart(OpTocLink) }
func (b *BookState) TocLinkIsComplete() bool         { return b.OpIsComplete(OpTocLink) }
func (b *BookState) GetTocLinkState() OperationState { return b.OpGetState(OpTocLink) }

func (b *BookState) TocFinalizeStart() error             { return b.OpStart(OpTocFinalize) }
func (b *BookState) TocFinalizeComplete()                { b.OpComplete(OpTocFinalize) }
func (b *BookState) TocFinalizeFail(maxRetries int) bool { return b.OpFail(OpTocFinalize, maxRetries) }
func (b *BookState) TocFinalizeReset()                   { b.OpReset(OpTocFinalize) }
func (b *BookState) TocFinalizeIsStarted() bool          { return b.OpIsStarted(OpTocFinalize) }
func (b *BookState) TocFinalizeIsDone() bool             { return b.OpIsDone(OpTocFinalize) }
func (b *BookState) TocFinalizeCanStart() bool           { return b.OpCanStart(OpTocFinalize) }
func (b *BookState) TocFinalizeIsComplete() bool         { return b.OpIsComplete(OpTocFinalize) }
func (b *BookState) GetTocFinalizeState() OperationState { return b.OpGetState(OpTocFinalize) }

func (b *BookState) StructureStart() error             { return b.OpStart(OpStructure) }
func (b *BookState) StructureComplete()                { b.OpComplete(OpStructure) }
func (b *BookState) StructureFail(maxRetries int) bool { return b.OpFail(OpStructure, maxRetries) }
func (b *BookState) StructureReset()                   { b.OpReset(OpStructure) }
func (b *BookState) StructureIsStarted() bool          { return b.OpIsStarted(OpStructure) }
func (b *BookState) StructureIsDone() bool             { return b.OpIsDone(OpStructure) }
func (b *BookState) StructureCanStart() bool           { return b.OpCanStart(OpStructure) }
func (b *BookState) StructureIsComplete() bool         { return b.OpIsComplete(OpStructure) }
func (b *BookState) GetStructureState() OperationState { return b.OpGetState(OpStructure) }

// --- Cost Tracking Accessors ---
// Write-through cache: costs are updated when work units complete.
// Lazy load: costs can be loaded from DB on first access if not already cached.

// AddCost adds a cost amount for a stage (thread-safe).
// Called by OnComplete handlers when work units finish.
func (b *BookState) AddCost(stage string, cost float64) {
	if cost <= 0 {
		return
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	b.costsByStage[stage] += cost
	b.totalCost += cost
}

// GetTotalCost returns the total accumulated cost (thread-safe).
func (b *BookState) GetTotalCost() float64 {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.totalCost
}

// GetCostByStage returns the cost for a specific stage (thread-safe).
func (b *BookState) GetCostByStage(stage string) float64 {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.costsByStage[stage]
}

// GetCostsByStage returns a copy of all costs by stage (thread-safe).
func (b *BookState) GetCostsByStage() map[string]float64 {
	b.mu.RLock()
	defer b.mu.RUnlock()
	result := make(map[string]float64, len(b.costsByStage))
	for k, v := range b.costsByStage {
		result[k] = v
	}
	return result
}

// SetCosts sets costs from loaded data (thread-safe).
// Used when loading costs from DB or restoring from checkpoint.
func (b *BookState) SetCosts(costsByStage map[string]float64, totalCost float64) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.costsByStage = make(map[string]float64, len(costsByStage))
	for k, v := range costsByStage {
		b.costsByStage[k] = v
	}
	b.totalCost = totalCost
	b.costsLoaded = true
}

// CostsLoaded returns true if costs have been loaded from DB (thread-safe).
func (b *BookState) CostsLoaded() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.costsLoaded
}

// GetTotalCostWithLazyLoad returns total cost, loading from DB if needed (thread-safe).
// Requires context with DefraClient for DB queries.
func (b *BookState) GetTotalCostWithLazyLoad(ctx context.Context) float64 {
	b.mu.RLock()
	if b.costsLoaded {
		cost := b.totalCost
		b.mu.RUnlock()
		return cost
	}
	b.mu.RUnlock()

	// Need to load from DB - upgrade to write lock
	b.mu.Lock()
	defer b.mu.Unlock()

	// Double-check after acquiring write lock
	if b.costsLoaded {
		return b.totalCost
	}

	// Load costs from DefraDB
	loadBookCostsFromDB(ctx, b)
	return b.totalCost
}

// --- Agent Run Accessors ---
// Write-through cache: agent runs are added when agents complete.
// Lazy load: agent runs can be loaded from DB on first access if not already cached.

// AddAgentRun adds an agent run summary to the cache (thread-safe).
// Called when an agent completes execution.
func (b *BookState) AddAgentRun(run AgentRunSummary) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.agentRuns = append(b.agentRuns, run)
}

// GetAgentRuns returns cached agent run summaries (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetAgentRuns() []AgentRunSummary {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.agentRuns == nil {
		return nil
	}
	result := make([]AgentRunSummary, len(b.agentRuns))
	copy(result, b.agentRuns)
	return result
}

// GetAgentRunCount returns the number of cached agent runs (thread-safe).
func (b *BookState) GetAgentRunCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.agentRuns)
}

// AgentRunsLoaded returns true if agent runs have been loaded from DB (thread-safe).
func (b *BookState) AgentRunsLoaded() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.agentRunsLoaded
}

// SetAgentRuns sets agent runs from loaded data (thread-safe).
// Used when loading agent runs from DB.
func (b *BookState) SetAgentRuns(runs []AgentRunSummary) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.agentRuns = make([]AgentRunSummary, len(runs))
	copy(b.agentRuns, runs)
	b.agentRunsLoaded = true
}

// GetAgentRunsWithLazyLoad returns agent runs, loading from DB if needed (thread-safe).
// Requires context with DefraClient for DB queries.
func (b *BookState) GetAgentRunsWithLazyLoad(ctx context.Context) []AgentRunSummary {
	b.mu.RLock()
	if b.agentRunsLoaded {
		runs := make([]AgentRunSummary, len(b.agentRuns))
		copy(runs, b.agentRuns)
		b.mu.RUnlock()
		return runs
	}
	b.mu.RUnlock()

	// Need to load from DB - upgrade to write lock
	b.mu.Lock()
	defer b.mu.Unlock()

	// Double-check after acquiring write lock
	if b.agentRunsLoaded {
		result := make([]AgentRunSummary, len(b.agentRuns))
		copy(result, b.agentRuns)
		return result
	}

	// Load agent runs from DefraDB
	loadAgentRunsFromDB(ctx, b)
	result := make([]AgentRunSummary, len(b.agentRuns))
	copy(result, b.agentRuns)
	return result
}
