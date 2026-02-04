package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// OpType identifies a book-level pipeline operation.
type OpType string

const (
	OpMetadata    OpType = "metadata"
	OpTocFinder   OpType = "toc_finder"
	OpTocExtract  OpType = "toc_extract"
	OpTocLink     OpType = "toc_link"
	OpTocFinalize OpType = "toc_finalize"
	OpStructure   OpType = "structure"
)

// AllOpTypes lists all operation types in pipeline order.
var AllOpTypes = []OpType{
	OpMetadata,
	OpTocFinder,
	OpTocExtract,
	OpTocLink,
	OpTocFinalize,
	OpStructure,
}

// OpConfig describes persistence, cascade, and reset behavior for an operation.
type OpConfig struct {
	// Collection is the DefraDB collection ("Book" or "ToC").
	Collection string

	// FieldPrefix is the DB field prefix (e.g. "metadata", "finder", "extract").
	FieldPrefix string

	// DocIDSource returns the document ID for persistence.
	// For Book operations this returns BookDocID; for ToC operations this returns TocDocID.
	DocIDSource func(b *BookState) string

	// CascadesTo lists operations that must be reset when this operation resets.
	CascadesTo []OpType

	// AgentTypes lists agent types to clear from memory and DB on reset.
	AgentTypes []string

	// ResetHook runs operation-specific cleanup during reset (e.g. deleting TocEntry records).
	// May be nil if no extra cleanup is needed.
	ResetHook func(ctx context.Context, book *BookState, tocDocID string) error

	// ResetDBFields contains extra DB fields to clear on reset, beyond the standard
	// started/complete/failed/retries fields. May be nil.
	ResetDBFields map[string]any

	// ResetMemoryHook runs in-memory state cleanup during reset.
	// May be nil if no extra memory cleanup is needed.
	ResetMemoryHook func(book *BookState)
}

// OpRegistry maps each operation type to its configuration.
var OpRegistry = map[OpType]*OpConfig{
	OpMetadata: {
		Collection:  "Book",
		FieldPrefix: "metadata",
		DocIDSource: func(b *BookState) string { return b.BookDocID },
		CascadesTo:  nil,
		AgentTypes:  []string{"metadata"},
	},
	OpTocFinder: {
		Collection:  "ToC",
		FieldPrefix: "finder",
		DocIDSource: func(b *BookState) string { return b.TocDocID() },
		CascadesTo:  []OpType{OpTocExtract},
		AgentTypes:  []string{"toc_finder"},
		ResetMemoryHook: func(book *BookState) {
			book.setTocFoundUnlocked(false)
			book.setTocPageRangeUnlocked(0, 0)
		},
		ResetDBFields: map[string]any{
			"toc_found":  false,
			"start_page": nil,
			"end_page":   nil,
		},
	},
	OpTocExtract: {
		Collection:  "ToC",
		FieldPrefix: "extract",
		DocIDSource: func(b *BookState) string { return b.TocDocID() },
		CascadesTo:  []OpType{OpTocLink},
		AgentTypes:  []string{"toc_extract"},
		ResetMemoryHook: func(book *BookState) {
			book.setTocEntriesUnlocked(nil)
		},
		ResetHook: resetTocExtractHook,
	},
	OpTocLink: {
		Collection:  "ToC",
		FieldPrefix: "link",
		DocIDSource: func(b *BookState) string { return b.TocDocID() },
		CascadesTo:  []OpType{OpTocFinalize},
		AgentTypes:  []string{AgentTypeTocEntryFinder, AgentTypeChapterFinder},
		ResetMemoryHook: func(book *BookState) {
			book.linkedEntries = nil
		},
		ResetHook: resetTocLinkHook,
	},
	OpTocFinalize: {
		Collection:  "ToC",
		FieldPrefix: "finalize",
		DocIDSource: func(b *BookState) string { return b.TocDocID() },
		CascadesTo:  []OpType{OpStructure},
		AgentTypes:  []string{AgentTypeGapInvestigator, AgentTypeChapterFinder},
		ResetMemoryHook: func(book *BookState) {
			book.finalizePhase = ""
			book.finalizePatternResult = nil
			book.entriesToFind = nil
			book.finalizeGaps = nil
			book.finalizeEntriesComplete = 0
			book.finalizeEntriesFound = 0
			book.finalizeGapsComplete = 0
			book.finalizeGapsFixes = 0
		},
	},
	OpStructure: {
		Collection:  "Book",
		FieldPrefix: "structure",
		DocIDSource: func(b *BookState) string { return b.BookDocID },
		CascadesTo:  nil,
		AgentTypes:  []string{"structure", "polish_chapter"},
		ResetMemoryHook: func(book *BookState) {
			book.structurePhase = ""
			book.structureChaptersTotal = 0
			book.structureChaptersExtracted = 0
			book.structureChaptersPolished = 0
			book.structurePolishFailed = 0
			book.structureChapters = nil
			book.structureClassifications = nil
			book.structureClassifyReasonings = nil
			book.structureClassifyPending = false
		},
		ResetHook: resetStructureHook,
		ResetDBFields: map[string]any{
			"structure_phase":              nil,
			"structure_chapters_total":     0,
			"structure_chapters_extracted": 0,
			"structure_chapters_polished":  0,
			"structure_polish_failed":      0,
			"total_chapters":               0,
			"total_paragraphs":             0,
			"total_words":                  0,
		},
	},
}

// --- Generic BookState Operation Methods ---

// OpStart starts the given operation (thread-safe).
func (b *BookState) OpStart(op OpType) error {
	if _, ok := OpRegistry[op]; !ok {
		return fmt.Errorf("unknown operation: %s", op)
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.ops[op].Start()
}

// OpComplete marks the given operation as complete (thread-safe).
func (b *BookState) OpComplete(op OpType) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.ops[op].Complete()
}

// PersistOpComplete marks operation complete and returns commit CID.
func PersistOpComplete(ctx context.Context, book *BookState, op OpType) (string, error) {
	cfg, ok := OpRegistry[op]
	if !ok || cfg == nil {
		return "", fmt.Errorf("unknown operation: %s", op)
	}

	docID := cfg.DocIDSource(book)
	if docID == "" {
		return "", fmt.Errorf("no doc ID for operation %s", op)
	}

	update := map[string]any{
		cfg.FieldPrefix + "_complete": true,
		cfg.FieldPrefix + "_started":  false,
	}

	if book.Store != nil {
		result, err := book.Store.SendSync(ctx, defra.WriteOp{
			Collection: cfg.Collection,
			DocID:      docID,
			Document:   update,
			Op:         defra.OpUpdate,
		})
		if err != nil {
			return "", err
		}
		if result.CID != "" {
			book.SetOperationCID(op, result.CID)
			if cfg.Collection == "Book" {
				book.SetBookCID(result.CID)
			} else if cfg.Collection == "ToC" {
				book.SetTocCID(result.CID)
			}
		}
		return result.CID, nil
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return "", fmt.Errorf("defra client not in context")
	}

	result, err := defraClient.UpdateWithVersion(ctx, cfg.Collection, docID, update)
	if err != nil {
		return "", err
	}

	if result.CID != "" {
		book.SetOperationCID(op, result.CID)
		if cfg.Collection == "Book" {
			book.SetBookCID(result.CID)
		} else if cfg.Collection == "ToC" {
			book.SetTocCID(result.CID)
		}
	}

	return result.CID, nil
}

// OpFail records a failure for the given operation (thread-safe).
// Returns true if the operation is permanently failed (max retries reached).
func (b *BookState) OpFail(op OpType, maxRetries int) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.ops[op].Fail(maxRetries)
}

// OpReset resets the given operation to not-started state (thread-safe).
func (b *BookState) OpReset(op OpType) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.ops[op].Reset()
}

// OpIsStarted returns true if the operation is in progress (thread-safe).
func (b *BookState) OpIsStarted(op OpType) bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.ops[op].IsStarted()
}

// OpIsDone returns true if the operation is complete or permanently failed (thread-safe).
func (b *BookState) OpIsDone(op OpType) bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.ops[op].IsDone()
}

// OpCanStart returns true if the operation can be started (thread-safe).
func (b *BookState) OpCanStart(op OpType) bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.ops[op].CanStart()
}

// OpIsComplete returns true if the operation completed successfully (thread-safe).
func (b *BookState) OpIsComplete(op OpType) bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.ops[op].IsComplete()
}

// OpGetState returns a copy of the operation state (thread-safe).
func (b *BookState) OpGetState(op OpType) OperationState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return *b.ops[op]
}

// SetOpState sets operation state from DB values (thread-safe).
// Used during LoadBookOperationState to populate state from DB booleans.
func (b *BookState) SetOpState(op OpType, started, complete, failed bool, retries int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	state := boolsToOpState(started, complete, failed, retries)
	*b.ops[op] = state
}

// TocDocID returns the ToC document ID.
// This delegates to the tocDocID field which is set during load.
func (b *BookState) TocDocID() string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocDocID
}

// SetTocDocID sets the ToC document ID (thread-safe).
func (b *BookState) SetTocDocID(docID string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocDocID = docID
	if b.tocCID != "" && docID != "" {
		b.trackCIDLocked("ToC", docID, b.tocCID)
	}
}

// --- Internal unlocked setters for use in ResetMemoryHook ---
// These must only be called while the caller holds b.mu.Lock().

func (b *BookState) setTocFoundUnlocked(found bool) {
	b.tocFound = found
}

func (b *BookState) setTocPageRangeUnlocked(start, end int) {
	b.tocStartPage = start
	b.tocEndPage = end
}

func (b *BookState) setTocEntriesUnlocked(entries interface{}) {
	b.tocEntries = nil
}

// --- Reset Hook Functions ---
// These are called from the generic reset path when operation-specific cleanup is needed.

// resetTocExtractHook deletes all TocEntry records for the ToC.
func resetTocExtractHook(ctx context.Context, book *BookState, tocDocID string) error {
	if tocDocID == "" {
		return nil
	}
	if book.Store != nil {
		return deleteCollectionDocsViaStore(ctx, book.Store, "TocEntry", "toc_id", tocDocID)
	}
	return deleteTocEntries(ctx, tocDocID)
}

// resetTocLinkHook clears actual_page links from ToC entries.
func resetTocLinkHook(ctx context.Context, book *BookState, tocDocID string) error {
	if tocDocID == "" {
		return nil
	}
	if book.Store != nil {
		return updateCollectionDocsViaStore(ctx, book.Store, "TocEntry", "toc_id", tocDocID, map[string]any{"actual_page_id": nil})
	}
	return clearTocEntryLinks(ctx, tocDocID)
}

// resetStructureHook deletes all Chapter records for the book.
func resetStructureHook(ctx context.Context, book *BookState, tocDocID string) error {
	if book.Store != nil {
		return deleteCollectionDocsViaStore(ctx, book.Store, "Chapter", "book_id", book.BookID)
	}
	return deleteChapters(ctx, book.BookID)
}
