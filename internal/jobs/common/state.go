package common

import (
	"encoding/json"
	"fmt"
	"log/slog"
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
	BookTitle string // From metadata extraction, may be empty if not yet extracted

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
	Metadata        OperationState
	TocFinder       OperationState
	TocExtract      OperationState
	PatternAnalysis OperationState
	TocLink         OperationState
	TocFinalize     OperationState
	Structure       OperationState

	// Structure phase tracking (mutable - use accessor methods)
	// Phases: build -> extract -> classify -> polish -> finalize
	StructurePhase             string
	StructureChaptersTotal     int
	StructureChaptersExtracted int
	StructureChaptersPolished  int
	StructurePolishFailed      int

	// Structure sub-job state (mutable - use accessor methods)
	StructureChapters        []*ChapterState
	StructureClassifications map[string]string // entry_id -> matter_type
	StructureClassifyPending bool

	// Finalize ToC sub-job state (mutable - use accessor methods)
	FinalizePhase           string
	FinalizePatternResult   *FinalizePatternResult
	EntriesToFind           []*EntryToFind
	FinalizeEntriesComplete int
	FinalizeEntriesFound    int
	FinalizeGaps            []*FinalizeGap
	FinalizeGapsComplete    int
	FinalizeGapsFixes       int

	// ToC finder results (mutable - use accessor methods)
	TocFound     bool
	TocStartPage int
	TocEndPage   int

	// ToC entries loaded from DB (immutable after LoadBook when ToC extraction is complete)
	TocEntries []*toc_entry_finder.TocEntry

	// Pattern analysis results (set after pattern analysis completes)
	PatternAnalysisResult *PagePatternResult

	// Pattern analysis intermediate results (mutable - use accessor methods)
	// These are populated during the 3-phase pattern analysis process:
	//   Phase 1: PageNumberPattern and ChapterPatterns are set independently
	//   Phase 2: Both are used to create the boundaries work unit
	//   Phase 3: All three are aggregated into PatternAnalysisResult
	PageNumberPattern *page_pattern_analyzer.PageNumberPattern
	ChapterPatterns   []page_pattern_analyzer.ChapterPattern

	// Body page range (set during finalize phase)
	BodyStart int
	BodyEnd   int

	// Agent states for job resume (mutable - use accessor methods)
	// Key format: "agent_type" for single agents, "agent_type:entry_doc_id" for per-entry agents
	AgentStates map[string]*AgentState
}

// NewBookState creates a new BookState with initialized maps.
func NewBookState(bookID string) *BookState {
	return &BookState{
		BookID:                   bookID,
		BookDocID:                bookID, // Same as BookID - both are the DefraDB document ID
		Pages:                    make(map[int]*PageState),
		Prompts:                  make(map[string]string),
		PromptCIDs:               make(map[string]string),
		AgentStates:              make(map[string]*AgentState),
		StructureClassifications: make(map[string]string),
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

// --- Thread-safe accessors for TocEntries ---

// GetTocEntries returns the ToC entries (thread-safe).
func (b *BookState) GetTocEntries() []*toc_entry_finder.TocEntry {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.TocEntries
}

// SetTocEntries sets the ToC entries (thread-safe).
func (b *BookState) SetTocEntries(entries []*toc_entry_finder.TocEntry) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.TocEntries = entries
}

// GetUnlinkedTocEntries returns only entries without actual_page linked.
// This filters the cached entries rather than re-querying DB.
func (b *BookState) GetUnlinkedTocEntries() []*toc_entry_finder.TocEntry {
	b.mu.RLock()
	defer b.mu.RUnlock()
	// TocEntries are already filtered to unlinked during load
	return b.TocEntries
}

// SetPageNumberPattern sets the page number pattern (thread-safe).
func (b *BookState) SetPageNumberPattern(pattern *page_pattern_analyzer.PageNumberPattern) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.PageNumberPattern = pattern
}

// GetPageNumberPattern gets the page number pattern (thread-safe).
func (b *BookState) GetPageNumberPattern() *page_pattern_analyzer.PageNumberPattern {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.PageNumberPattern
}

// SetChapterPatterns sets the chapter patterns (thread-safe).
func (b *BookState) SetChapterPatterns(patterns []page_pattern_analyzer.ChapterPattern) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.ChapterPatterns = patterns
}

// GetChapterPatterns gets the chapter patterns (thread-safe).
func (b *BookState) GetChapterPatterns() []page_pattern_analyzer.ChapterPattern {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.ChapterPatterns
}

// SetStructurePhase sets the current structure processing phase (thread-safe).
func (b *BookState) SetStructurePhase(phase string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.StructurePhase = phase
}

// GetStructurePhase gets the current structure processing phase (thread-safe).
func (b *BookState) GetStructurePhase() string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.StructurePhase
}

// SetStructureProgress sets the structure progress counters (thread-safe).
func (b *BookState) SetStructureProgress(total, extracted, polished, failed int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.StructureChaptersTotal = total
	b.StructureChaptersExtracted = extracted
	b.StructureChaptersPolished = polished
	b.StructurePolishFailed = failed
}

// GetStructureProgress gets the structure progress counters (thread-safe).
func (b *BookState) GetStructureProgress() (total, extracted, polished, failed int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.StructureChaptersTotal, b.StructureChaptersExtracted, b.StructureChaptersPolished, b.StructurePolishFailed
}

// IncrementStructurePolished increments the polished counter (thread-safe).
func (b *BookState) IncrementStructurePolished() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.StructureChaptersPolished++
}

// IncrementStructurePolishFailed increments the polish failed counter (thread-safe).
func (b *BookState) IncrementStructurePolishFailed() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.StructurePolishFailed++
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
	return b.AgentStates[key]
}

// SetAgentState stores agent state (thread-safe).
func (b *BookState) SetAgentState(state *AgentState) {
	b.mu.Lock()
	defer b.mu.Unlock()
	key := AgentStateKey(state.AgentType, state.EntryDocID)
	b.AgentStates[key] = state
}

// RemoveAgentState removes agent state (thread-safe).
func (b *BookState) RemoveAgentState(agentType string, entryDocID string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	key := AgentStateKey(agentType, entryDocID)
	delete(b.AgentStates, key)
}

// GetAllAgentStates returns all agent states (thread-safe, returns a copy of keys).
func (b *BookState) GetAllAgentStates() []*AgentState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	states := make([]*AgentState, 0, len(b.AgentStates))
	for _, state := range b.AgentStates {
		states = append(states, state)
	}
	return states
}

// ClearAgentStates removes all agent states for a given type (thread-safe).
// Use this when resetting an operation to clear associated agent state.
func (b *BookState) ClearAgentStates(agentType string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for key := range b.AgentStates {
		// Match exact type or type: prefix for per-entry agents
		if key == agentType || (len(key) > len(agentType) && key[:len(agentType)+1] == agentType+":") {
			delete(b.AgentStates, key)
		}
	}
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
	return b.FinalizePhase
}

// SetFinalizePhase sets the current finalize phase (thread-safe).
func (b *BookState) SetFinalizePhase(phase string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.FinalizePhase = phase
}

// GetFinalizePatternResult returns the finalize pattern result (thread-safe).
func (b *BookState) GetFinalizePatternResult() *FinalizePatternResult {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.FinalizePatternResult
}

// SetFinalizePatternResult sets the finalize pattern result (thread-safe).
func (b *BookState) SetFinalizePatternResult(result *FinalizePatternResult) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.FinalizePatternResult = result
}

// GetEntriesToFind returns entries to find in discover phase (thread-safe).
func (b *BookState) GetEntriesToFind() []*EntryToFind {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.EntriesToFind
}

// SetEntriesToFind sets entries to find in discover phase (thread-safe).
func (b *BookState) SetEntriesToFind(entries []*EntryToFind) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.EntriesToFind = entries
}

// GetFinalizeGaps returns gaps to investigate (thread-safe).
func (b *BookState) GetFinalizeGaps() []*FinalizeGap {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.FinalizeGaps
}

// SetFinalizeGaps sets gaps to investigate (thread-safe).
func (b *BookState) SetFinalizeGaps(gaps []*FinalizeGap) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.FinalizeGaps = gaps
}

// GetFinalizeProgress returns finalize progress counters (thread-safe).
func (b *BookState) GetFinalizeProgress() (entriesComplete, entriesFound, gapsComplete, gapsFixes int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.FinalizeEntriesComplete, b.FinalizeEntriesFound, b.FinalizeGapsComplete, b.FinalizeGapsFixes
}

// SetFinalizeProgress sets finalize progress counters (thread-safe).
func (b *BookState) SetFinalizeProgress(entriesComplete, entriesFound, gapsComplete, gapsFixes int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.FinalizeEntriesComplete = entriesComplete
	b.FinalizeEntriesFound = entriesFound
	b.FinalizeGapsComplete = gapsComplete
	b.FinalizeGapsFixes = gapsFixes
}

// IncrementFinalizeEntriesComplete increments entries complete (thread-safe).
func (b *BookState) IncrementFinalizeEntriesComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.FinalizeEntriesComplete++
}

// IncrementFinalizeEntriesFound increments entries found (thread-safe).
func (b *BookState) IncrementFinalizeEntriesFound() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.FinalizeEntriesFound++
}

// IncrementFinalizeGapsComplete increments gaps complete (thread-safe).
func (b *BookState) IncrementFinalizeGapsComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.FinalizeGapsComplete++
}

// IncrementFinalizeGapsFixes increments gaps fixed (thread-safe).
func (b *BookState) IncrementFinalizeGapsFixes() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.FinalizeGapsFixes++
}

// --- Structure State Types ---

// ChapterState tracks chapter during structure processing.
type ChapterState struct {
	// Identity
	EntryID string `json:"entry_id"` // Unique within book (e.g., "ch_001")
	DocID   string `json:"doc_id"`   // DefraDB doc ID (after create)

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
	ExtractDone bool `json:"extract_done"`
	PolishDone  bool `json:"polish_done"`
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
func (b *BookState) GetStructureChapters() []*ChapterState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.StructureChapters
}

// SetStructureChapters sets the structure chapters (thread-safe).
func (b *BookState) SetStructureChapters(chapters []*ChapterState) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.StructureChapters = chapters
}

// GetStructureClassifications returns the matter classifications (thread-safe).
func (b *BookState) GetStructureClassifications() map[string]string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.StructureClassifications
}

// SetStructureClassifications sets the matter classifications (thread-safe).
func (b *BookState) SetStructureClassifications(classifications map[string]string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.StructureClassifications = classifications
}

// GetStructureClassifyPending returns whether classification is pending (thread-safe).
func (b *BookState) GetStructureClassifyPending() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.StructureClassifyPending
}

// SetStructureClassifyPending sets whether classification is pending (thread-safe).
func (b *BookState) SetStructureClassifyPending(pending bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.StructureClassifyPending = pending
}

// GetChapterByEntryID returns a chapter by its entry ID (thread-safe).
func (b *BookState) GetChapterByEntryID(entryID string) *ChapterState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	for _, ch := range b.StructureChapters {
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
	for i, ch := range b.StructureChapters {
		if ch.EntryID == chapter.EntryID {
			b.StructureChapters[i] = chapter
			return
		}
	}
}
