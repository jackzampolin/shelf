package common

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync"

	page_pattern_analyzer "github.com/jackzampolin/shelf/internal/agents/page_pattern_analyzer"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/home"
)

// HomeDir is an alias for home.Dir for external use.
type HomeDir = home.Dir

// PagePatternResult is an alias for the pattern analysis result.
type PagePatternResult = page_pattern_analyzer.Result

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

	// Cached data fields (populated on write-through or lazy load from DB)
	// These avoid re-querying DB for data we just wrote or need repeatedly.
	headings        []HeadingItem // Parsed headings from blend_markdown
	pageNumberLabel *string       // nil = not loaded, empty string = loaded but no label
	runningHeader   *string       // nil = not loaded
	isTocPage       *bool         // nil = not loaded, true/false = loaded
	dataLoaded      bool          // True if blend_markdown/headings/labels loaded from DB
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

// --- Cache accessor methods ---

// GetHeadings returns the cached headings (thread-safe).
func (p *PageState) GetHeadings() []HeadingItem {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.headings
}

// SetHeadings sets the cached headings (thread-safe).
func (p *PageState) SetHeadings(headings []HeadingItem) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.headings = headings
}

// GetPageNumberLabel returns the cached page number label (thread-safe).
// Returns nil if not loaded from DB.
func (p *PageState) GetPageNumberLabel() *string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.pageNumberLabel
}

// SetPageNumberLabel sets the cached page number label (thread-safe).
func (p *PageState) SetPageNumberLabel(label *string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.pageNumberLabel = label
}

// GetRunningHeader returns the cached running header (thread-safe).
// Returns nil if not loaded from DB.
func (p *PageState) GetRunningHeader() *string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.runningHeader
}

// SetRunningHeader sets the cached running header (thread-safe).
func (p *PageState) SetRunningHeader(header *string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.runningHeader = header
}

// GetIsTocPage returns the cached is_toc_page flag (thread-safe).
// Returns nil if not loaded from DB.
func (p *PageState) GetIsTocPage() *bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.isTocPage
}

// SetIsTocPage sets the cached is_toc_page flag (thread-safe).
func (p *PageState) SetIsTocPage(isTocPage *bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.isTocPage = isTocPage
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

// SetBlendResultWithHeadings sets the blend result and headings together (thread-safe).
// Use this for write-through caching when persisting blend results.
func (p *PageState) SetBlendResultWithHeadings(blendedText string, headings []HeadingItem) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.blendedText = blendedText
	p.headings = headings
	p.blendDone = true
	p.dataLoaded = true // Mark as loaded since we have the data
}

// SetLabelResultCached sets the label results in cache (thread-safe).
// Use this for write-through caching when persisting label results.
func (p *PageState) SetLabelResultCached(pageNumberLabel, runningHeader *string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.pageNumberLabel = pageNumberLabel
	p.runningHeader = runningHeader
	p.labelDone = true
}

// PopulateFromDBResult populates cache fields from a DB query result map.
// This is used for lazy loading and batch preloading.
func (p *PageState) PopulateFromDBResult(data map[string]any) {
	p.mu.Lock()
	defer p.mu.Unlock()

	if bm, ok := data["blend_markdown"].(string); ok {
		p.blendedText = bm
	}

	if h, ok := data["headings"].(string); ok && h != "" {
		var headings []HeadingItem
		if err := json.Unmarshal([]byte(h), &headings); err != nil {
			slog.Debug("failed to parse headings JSON in PopulateFromDBResult",
				"error", err)
		} else {
			p.headings = headings
		}
	}

	if pnl, ok := data["page_number_label"].(string); ok {
		p.pageNumberLabel = &pnl
	}

	if rh, ok := data["running_header"].(string); ok {
		p.runningHeader = &rh
	}

	if isToc, ok := data["is_toc_page"].(bool); ok {
		p.isTocPage = &isToc
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

	// Pipeline stage toggles (immutable after LoadBook)
	// Used by variants to enable/disable stages
	EnableOCR             bool
	EnableBlend           bool
	EnableLabel           bool
	EnableMetadata        bool
	EnableTocFinder       bool
	EnableTocExtract      bool
	EnablePatternAnalysis bool
	EnableTocLink         bool
	EnableTocFinalize     bool
	EnableStructure       bool

	// Resolved prompts (immutable after LoadBook)
	Prompts    map[string]string // prompt_key -> resolved text
	PromptCIDs map[string]string // prompt_key -> CID for traceability

	// Book-level operation state (mutable - unexported, use accessor methods)
	metadata        OperationState
	tocFinder       OperationState
	tocExtract      OperationState
	patternAnalysis OperationState
	tocLink         OperationState
	tocFinalize     OperationState
	structure       OperationState

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

	// Pattern analysis results (unexported, use accessor methods)
	patternAnalysisResult *PagePatternResult

	// Pattern analysis intermediate results (mutable - unexported, use accessor methods)
	// These are populated during the 3-phase pattern analysis process:
	//   Phase 1: PageNumberPattern and ChapterPatterns are set independently
	//   Phase 2: Both are used to create the boundaries work unit
	//   Phase 3: All three are aggregated into PatternAnalysisResult
	pageNumberPattern *page_pattern_analyzer.PageNumberPattern
	chapterPatterns   []page_pattern_analyzer.ChapterPattern

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
}

// NewBookState creates a new BookState with initialized maps.
func NewBookState(bookID string) *BookState {
	return &BookState{
		BookID:                      bookID,
		BookDocID:                   bookID, // Same as BookID - both are the DefraDB document ID
		Pages:                       make(map[int]*PageState),
		Prompts:                     make(map[string]string),
		PromptCIDs:                  make(map[string]string),
		agentStates:                 make(map[string]*AgentState),
		structureClassifications:    make(map[string]string),
		structureClassifyReasonings: make(map[string]string),
		costsByStage:                make(map[string]float64),
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

// CountBlendedPages returns the number of pages that have completed blend.
func (b *BookState) CountBlendedPages() int {
	count := 0
	b.ForEachPage(func(pageNum int, state *PageState) {
		if state.IsBlendDone() {
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

// AllPagesBlendComplete returns true if all pages have completed blend.
func (b *BookState) AllPagesBlendComplete() bool {
	allDone := true
	b.ForEachPage(func(pageNum int, state *PageState) {
		if !state.IsBlendDone() {
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

// SetPageNumberPattern sets the page number pattern (thread-safe).
func (b *BookState) SetPageNumberPattern(pattern *page_pattern_analyzer.PageNumberPattern) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.pageNumberPattern = pattern
}

// GetPageNumberPattern gets the page number pattern (thread-safe).
func (b *BookState) GetPageNumberPattern() *page_pattern_analyzer.PageNumberPattern {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.pageNumberPattern
}

// SetChapterPatterns sets the chapter patterns (thread-safe).
func (b *BookState) SetChapterPatterns(patterns []page_pattern_analyzer.ChapterPattern) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.chapterPatterns = patterns
}

// GetChapterPatterns gets the chapter patterns (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetChapterPatterns() []page_pattern_analyzer.ChapterPattern {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.chapterPatterns == nil {
		return nil
	}
	result := make([]page_pattern_analyzer.ChapterPattern, len(b.chapterPatterns))
	copy(result, b.chapterPatterns)
	return result
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
}

// Valid agent types - used for validation
const (
	AgentTypeTocFinder      = "toc_finder"
	AgentTypeTocEntryFinder = "toc_entry_finder"
	AgentTypeChapterFinder  = "chapter_finder"
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
	Key              string `json:"key"`                // Unique key like "chapter_14"
	LevelName        string `json:"level_name"`         // "chapter", "part"
	Identifier       string `json:"identifier"`         // "14", "III", "A"
	HeadingFormat    string `json:"heading_format"`     // "Chapter {n}"
	Level            int    `json:"level"`
	ExpectedNearPage int    `json:"expected_near_page"` // Estimated page based on sequence
	SearchRangeStart int    `json:"search_range_start"`
	SearchRangeEnd   int    `json:"search_range_end"`
}

// FinalizeGap represents a gap in page coverage between entries.
type FinalizeGap struct {
	Key            string `json:"key"`              // Unique key like "gap_100_150"
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
	Phase           string                 `json:"phase"`            // pattern, discover, validate
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
	Phase              string                    `json:"phase"` // build, extract, classify, polish, finalize
	Chapters           []*ChapterState           `json:"chapters"`
	ChaptersToExtract  int                       `json:"chapters_to_extract"`
	ChaptersExtracted  int                       `json:"chapters_extracted"`
	ExtractsFailed     int                       `json:"extracts_failed"`
	ClassifyPending    bool                      `json:"classify_pending"`
	Classifications    map[string]string         `json:"classifications"`     // entry_id -> matter_type
	ClassifyReasonings map[string]string         `json:"classify_reasonings"` // entry_id -> reasoning
	ChaptersToPolish   int                       `json:"chapters_to_polish"`
	ChaptersPolished   int                       `json:"chapters_polished"`
	PolishFailed       int                       `json:"polish_failed"`
}

// GetStructureChapters returns the structure chapters (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetStructureChapters() []*ChapterState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.structureChapters == nil {
		return nil
	}
	result := make([]*ChapterState, len(b.structureChapters))
	copy(result, b.structureChapters)
	return result
}

// SetStructureChapters sets the structure chapters (thread-safe).
func (b *BookState) SetStructureChapters(chapters []*ChapterState) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureChapters = chapters
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

// GetChapterByEntryID returns a chapter by its entry ID (thread-safe).
func (b *BookState) GetChapterByEntryID(entryID string) *ChapterState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	for _, ch := range b.structureChapters {
		if ch.EntryID == entryID {
			return ch
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
func (b *BookState) GetStructureClassifyReasonings() map[string]string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structureClassifyReasonings
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

// --- Pattern Analysis Result Accessors ---

// GetPatternAnalysisResult returns the pattern analysis result (thread-safe).
func (b *BookState) GetPatternAnalysisResult() *PagePatternResult {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.patternAnalysisResult
}

// SetPatternAnalysisResult sets the pattern analysis result (thread-safe).
func (b *BookState) SetPatternAnalysisResult(result *PagePatternResult) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.patternAnalysisResult = result
}

// --- Operation State Accessors ---
// These provide thread-safe access to OperationState fields.
// Each book-level operation (Metadata, TocFinder, etc.) has its own state.

// MetadataStart starts the metadata operation (thread-safe).
func (b *BookState) MetadataStart() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.metadata.Start()
}

// MetadataComplete marks metadata as complete (thread-safe).
func (b *BookState) MetadataComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.metadata.Complete()
}

// MetadataFail records a metadata failure (thread-safe).
func (b *BookState) MetadataFail(maxRetries int) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.metadata.Fail(maxRetries)
}

// MetadataReset resets metadata state (thread-safe).
func (b *BookState) MetadataReset() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.metadata.Reset()
}

// MetadataIsStarted returns true if metadata is started (thread-safe).
func (b *BookState) MetadataIsStarted() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.metadata.IsStarted()
}

// MetadataIsDone returns true if metadata is done (thread-safe).
func (b *BookState) MetadataIsDone() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.metadata.IsDone()
}

// MetadataCanStart returns true if metadata can start (thread-safe).
func (b *BookState) MetadataCanStart() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.metadata.CanStart()
}

// MetadataIsComplete returns true if metadata completed successfully (thread-safe).
func (b *BookState) MetadataIsComplete() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.metadata.IsComplete()
}

// GetMetadataState returns a copy of the metadata operation state (thread-safe).
func (b *BookState) GetMetadataState() OperationState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.metadata
}

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
	b.bookMetadata = loadBookMetadataFromDB(ctx, b.BookID)
	b.bookMetadataLoaded = true
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

// TocFinderStart starts the ToC finder operation (thread-safe).
func (b *BookState) TocFinderStart() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.tocFinder.Start()
}

// TocFinderComplete marks ToC finder as complete (thread-safe).
func (b *BookState) TocFinderComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocFinder.Complete()
}

// TocFinderFail records a ToC finder failure (thread-safe).
func (b *BookState) TocFinderFail(maxRetries int) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.tocFinder.Fail(maxRetries)
}

// TocFinderReset resets ToC finder state (thread-safe).
func (b *BookState) TocFinderReset() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocFinder.Reset()
}

// TocFinderIsStarted returns true if ToC finder is started (thread-safe).
func (b *BookState) TocFinderIsStarted() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFinder.IsStarted()
}

// TocFinderIsDone returns true if ToC finder is done (thread-safe).
func (b *BookState) TocFinderIsDone() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFinder.IsDone()
}

// TocFinderCanStart returns true if ToC finder can start (thread-safe).
func (b *BookState) TocFinderCanStart() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFinder.CanStart()
}

// TocFinderIsComplete returns true if ToC finder completed successfully (thread-safe).
func (b *BookState) TocFinderIsComplete() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFinder.IsComplete()
}

// GetTocFinderState returns a copy of the ToC finder operation state (thread-safe).
func (b *BookState) GetTocFinderState() OperationState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFinder
}

// TocExtractStart starts the ToC extract operation (thread-safe).
func (b *BookState) TocExtractStart() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.tocExtract.Start()
}

// TocExtractComplete marks ToC extract as complete (thread-safe).
func (b *BookState) TocExtractComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocExtract.Complete()
}

// TocExtractFail records a ToC extract failure (thread-safe).
func (b *BookState) TocExtractFail(maxRetries int) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.tocExtract.Fail(maxRetries)
}

// TocExtractReset resets ToC extract state (thread-safe).
func (b *BookState) TocExtractReset() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocExtract.Reset()
}

// TocExtractIsStarted returns true if ToC extract is started (thread-safe).
func (b *BookState) TocExtractIsStarted() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocExtract.IsStarted()
}

// TocExtractIsDone returns true if ToC extract is done (thread-safe).
func (b *BookState) TocExtractIsDone() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocExtract.IsDone()
}

// TocExtractCanStart returns true if ToC extract can start (thread-safe).
func (b *BookState) TocExtractCanStart() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocExtract.CanStart()
}

// TocExtractIsComplete returns true if ToC extract completed successfully (thread-safe).
func (b *BookState) TocExtractIsComplete() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocExtract.IsComplete()
}

// GetTocExtractState returns a copy of the ToC extract operation state (thread-safe).
func (b *BookState) GetTocExtractState() OperationState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocExtract
}

// PatternAnalysisStart starts the pattern analysis operation (thread-safe).
func (b *BookState) PatternAnalysisStart() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.patternAnalysis.Start()
}

// PatternAnalysisComplete marks pattern analysis as complete (thread-safe).
func (b *BookState) PatternAnalysisComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.patternAnalysis.Complete()
}

// PatternAnalysisFail records a pattern analysis failure (thread-safe).
func (b *BookState) PatternAnalysisFail(maxRetries int) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.patternAnalysis.Fail(maxRetries)
}

// PatternAnalysisReset resets pattern analysis state (thread-safe).
func (b *BookState) PatternAnalysisReset() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.patternAnalysis.Reset()
}

// PatternAnalysisIsStarted returns true if pattern analysis is started (thread-safe).
func (b *BookState) PatternAnalysisIsStarted() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.patternAnalysis.IsStarted()
}

// PatternAnalysisIsDone returns true if pattern analysis is done (thread-safe).
func (b *BookState) PatternAnalysisIsDone() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.patternAnalysis.IsDone()
}

// PatternAnalysisCanStart returns true if pattern analysis can start (thread-safe).
func (b *BookState) PatternAnalysisCanStart() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.patternAnalysis.CanStart()
}

// PatternAnalysisIsComplete returns true if pattern analysis completed successfully (thread-safe).
func (b *BookState) PatternAnalysisIsComplete() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.patternAnalysis.IsComplete()
}

// GetPatternAnalysisState returns a copy of the pattern analysis operation state (thread-safe).
func (b *BookState) GetPatternAnalysisState() OperationState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.patternAnalysis
}

// TocLinkStart starts the ToC link operation (thread-safe).
func (b *BookState) TocLinkStart() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.tocLink.Start()
}

// TocLinkComplete marks ToC link as complete (thread-safe).
func (b *BookState) TocLinkComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocLink.Complete()
}

// TocLinkFail records a ToC link failure (thread-safe).
func (b *BookState) TocLinkFail(maxRetries int) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.tocLink.Fail(maxRetries)
}

// TocLinkReset resets ToC link state (thread-safe).
func (b *BookState) TocLinkReset() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocLink.Reset()
}

// TocLinkIsStarted returns true if ToC link is started (thread-safe).
func (b *BookState) TocLinkIsStarted() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocLink.IsStarted()
}

// TocLinkIsDone returns true if ToC link is done (thread-safe).
func (b *BookState) TocLinkIsDone() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocLink.IsDone()
}

// TocLinkCanStart returns true if ToC link can start (thread-safe).
func (b *BookState) TocLinkCanStart() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocLink.CanStart()
}

// TocLinkIsComplete returns true if ToC link completed successfully (thread-safe).
func (b *BookState) TocLinkIsComplete() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocLink.IsComplete()
}

// GetTocLinkState returns a copy of the ToC link operation state (thread-safe).
func (b *BookState) GetTocLinkState() OperationState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocLink
}

// TocFinalizeStart starts the ToC finalize operation (thread-safe).
func (b *BookState) TocFinalizeStart() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.tocFinalize.Start()
}

// TocFinalizeComplete marks ToC finalize as complete (thread-safe).
func (b *BookState) TocFinalizeComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocFinalize.Complete()
}

// TocFinalizeFail records a ToC finalize failure (thread-safe).
func (b *BookState) TocFinalizeFail(maxRetries int) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.tocFinalize.Fail(maxRetries)
}

// TocFinalizeReset resets ToC finalize state (thread-safe).
func (b *BookState) TocFinalizeReset() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocFinalize.Reset()
}

// TocFinalizeIsStarted returns true if ToC finalize is started (thread-safe).
func (b *BookState) TocFinalizeIsStarted() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFinalize.IsStarted()
}

// TocFinalizeIsDone returns true if ToC finalize is done (thread-safe).
func (b *BookState) TocFinalizeIsDone() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFinalize.IsDone()
}

// TocFinalizeCanStart returns true if ToC finalize can start (thread-safe).
func (b *BookState) TocFinalizeCanStart() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFinalize.CanStart()
}

// TocFinalizeIsComplete returns true if ToC finalize completed successfully (thread-safe).
func (b *BookState) TocFinalizeIsComplete() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFinalize.IsComplete()
}

// GetTocFinalizeState returns a copy of the ToC finalize operation state (thread-safe).
func (b *BookState) GetTocFinalizeState() OperationState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFinalize
}

// StructureStart starts the structure operation (thread-safe).
func (b *BookState) StructureStart() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.structure.Start()
}

// StructureComplete marks structure as complete (thread-safe).
func (b *BookState) StructureComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structure.Complete()
}

// StructureFail records a structure failure (thread-safe).
func (b *BookState) StructureFail(maxRetries int) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.structure.Fail(maxRetries)
}

// StructureReset resets structure state (thread-safe).
func (b *BookState) StructureReset() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structure.Reset()
}

// StructureIsStarted returns true if structure is started (thread-safe).
func (b *BookState) StructureIsStarted() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structure.IsStarted()
}

// StructureIsDone returns true if structure is done (thread-safe).
func (b *BookState) StructureIsDone() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structure.IsDone()
}

// StructureCanStart returns true if structure can start (thread-safe).
func (b *BookState) StructureCanStart() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structure.CanStart()
}

// StructureIsComplete returns true if structure completed successfully (thread-safe).
func (b *BookState) StructureIsComplete() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structure.IsComplete()
}

// GetStructureState returns a copy of the structure operation state (thread-safe).
func (b *BookState) GetStructureState() OperationState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structure
}

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
