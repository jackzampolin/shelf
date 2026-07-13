package common

import (
	"sync"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/home"
)

// HomeDir is an alias for home.Dir for external use.
type HomeDir = home.Dir

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
	finalizeEntriesTotal    int // Total entries to find (from pattern analysis)
	finalizeEntriesComplete int
	finalizeEntriesFound    int
	finalizeGaps            []*FinalizeGap
	finalizeGapsTotal       int // Total gaps to investigate
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
