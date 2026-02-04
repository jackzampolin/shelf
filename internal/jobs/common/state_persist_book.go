package common

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// getStore returns the StateStore to use for persistence.
// If b.Store is set, uses it directly. Otherwise builds an ad-hoc store from context.
// Returns nil if neither is available.
func (b *BookState) getStore(ctx context.Context) StateStore {
	if b.Store != nil {
		return b.Store
	}
	// Fallback: build ad-hoc store from context (for unmigrated code paths)
	client := svcctx.DefraClientFrom(ctx)
	sink := svcctx.DefraSinkFrom(ctx)
	if client != nil && sink != nil {
		slog.Warn("BookState using fallback store from context - consider setting b.Store directly",
			"book_id", b.BookID)
		return &DefraStateStore{Client: client, Sink: sink}
	}
	return nil
}

// PersistBookStatus updates book status in DB and memory. Returns CID.
//
// Deprecated: Use PersistBookStatusAsync instead for better latency.
// This sync version blocks on DB write; async version fires and forgets.
func (b *BookState) PersistBookStatus(ctx context.Context, status string) (string, error) {
	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      b.BookID,
		Document: map[string]any{
			"status": status,
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return "", err
	}

	b.mu.Lock()
	b.trackCIDLocked("Book", b.BookID, result.CID)
	b.bookCID = result.CID
	b.mu.Unlock()

	return result.CID, nil
}

// PersistBookStatusAsync fires and forgets book status update to DB.
// Note: CID tracking is skipped for async writes - memory is authoritative during execution.
func (b *BookState) PersistBookStatusAsync(ctx context.Context, status string) {
	store := b.getStore(ctx)
	if store == nil {
		slog.Error("PersistBookStatusAsync: no store available", "book_id", b.BookID)
		return
	}

	store.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      b.BookID,
		Document: map[string]any{
			"status": status,
		},
		Op:     defra.OpUpdate,
		Source: "PersistBookStatusAsync",
	})
}

// PersistMetadataResult saves metadata to Book record and updates b.bookMetadata.
//
// Deprecated: Use PersistMetadataResultAsync instead for better latency.
// This sync version blocks on DB write; async version fires and forgets.
func (b *BookState) PersistMetadataResult(ctx context.Context, result *BookMetadata, fields map[string]any) (string, error) {
	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	writeResult, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      b.BookID,
		Document:   fields,
		Op:         defra.OpUpdate,
	})
	if err != nil {
		return "", err
	}

	b.mu.Lock()
	b.bookMetadata = result
	b.bookMetadataLoaded = true
	b.trackCIDLocked("Book", b.BookID, writeResult.CID)
	b.bookCID = writeResult.CID
	b.mu.Unlock()

	return writeResult.CID, nil
}

// PersistMetadataResultAsync saves metadata to Book record with fire-and-forget DB write.
// Updates memory immediately, fires DB write in background.
// Note: CID tracking is skipped for async writes - memory is authoritative during execution.
func (b *BookState) PersistMetadataResultAsync(ctx context.Context, result *BookMetadata, fields map[string]any) {
	// Update memory first (atomic, under lock)
	b.mu.Lock()
	b.bookMetadata = result
	b.bookMetadataLoaded = true
	b.mu.Unlock()

	store := b.getStore(ctx)
	if store == nil {
		slog.Error("PersistMetadataResultAsync: no store available", "book_id", b.BookID)
		return
	}

	// Fire-and-forget DB write
	store.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      b.BookID,
		Document:   fields,
		Op:         defra.OpUpdate,
		Source:     "PersistMetadataResultAsync",
	})
}

// PersistOpState persists operation state (started/complete/failed/retries) for any operation type.
// If the target document doesn't exist yet (e.g., ToC record not created), returns nil without error.
// This allows callers to call PersistOpState at any time without managing document lifecycle.
//
// Deprecated: Use PersistOpStateAsync instead for better latency.
// This sync version blocks on DB write; async version fires and forgets.
func (b *BookState) PersistOpState(ctx context.Context, op OpType) error {
	cfg, ok := OpRegistry[op]
	if !ok {
		return fmt.Errorf("PersistOpState: unknown operation: %s", op)
	}

	state := b.OpGetState(op)
	docID := cfg.DocIDSource(b)
	if docID == "" {
		// No document exists yet - this is expected for operations like toc_finder
		// before the ToC record is created. Log for visibility.
		slog.Debug("PersistOpState skipped: no document yet",
			"book_id", b.BookID, "operation", op, "collection", cfg.Collection)
		return nil
	}

	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: cfg.Collection,
		DocID:      docID,
		Document: map[string]any{
			cfg.FieldPrefix + "_started":  state.IsStarted(),
			cfg.FieldPrefix + "_complete": state.IsComplete(),
			cfg.FieldPrefix + "_failed":   state.IsFailed(),
			cfg.FieldPrefix + "_retries":  state.GetRetries(),
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return err
	}

	b.mu.Lock()
	b.trackCIDLocked(cfg.Collection, docID, result.CID)
	if cfg.Collection == "Book" {
		b.bookCID = result.CID
	} else if cfg.Collection == "ToC" {
		b.tocCID = result.CID
	}
	b.mu.Unlock()

	return nil
}

// PersistOpComplete marks an operation complete and persists. Returns (CID, error).
//
// Deprecated: Use PersistOpCompleteAsync instead for better latency.
// This sync version blocks on DB write; async version fires and forgets.
func (b *BookState) PersistOpComplete(ctx context.Context, op OpType) (string, error) {
	cfg, ok := OpRegistry[op]
	if !ok || cfg == nil {
		return "", fmt.Errorf("unknown operation: %s", op)
	}

	docID := cfg.DocIDSource(b)
	if docID == "" {
		return "", fmt.Errorf("no doc ID for operation %s", op)
	}

	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	update := map[string]any{
		cfg.FieldPrefix + "_complete": true,
		cfg.FieldPrefix + "_started":  false,
	}

	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: cfg.Collection,
		DocID:      docID,
		Document:   update,
		Op:         defra.OpUpdate,
	})
	if err != nil {
		return "", err
	}

	b.mu.Lock()
	b.trackCIDLocked(cfg.Collection, docID, result.CID)
	if b.operationCIDs == nil {
		b.operationCIDs = make(map[OpType]string)
	}
	b.operationCIDs[op] = result.CID
	if cfg.Collection == "Book" {
		b.bookCID = result.CID
	} else if cfg.Collection == "ToC" {
		b.tocCID = result.CID
	}
	b.mu.Unlock()

	return result.CID, nil
}

// PersistOpCompleteAsync marks an operation complete and fires DB write without blocking.
// Updates memory immediately with placeholder CID, fires DB write in background.
// Note: CID tracking is skipped for async writes - memory is authoritative during execution.
func (b *BookState) PersistOpCompleteAsync(ctx context.Context, op OpType) {
	cfg, ok := OpRegistry[op]
	if !ok || cfg == nil {
		slog.Error("PersistOpCompleteAsync: unknown operation", "operation", op, "book_id", b.BookID)
		return
	}

	docID := cfg.DocIDSource(b)
	if docID == "" {
		slog.Warn("PersistOpCompleteAsync: no doc ID for operation", "operation", op, "book_id", b.BookID)
		return
	}

	store := b.getStore(ctx)
	if store == nil {
		slog.Error("PersistOpCompleteAsync: no store available", "book_id", b.BookID, "operation", op)
		return
	}

	update := map[string]any{
		cfg.FieldPrefix + "_complete": true,
		cfg.FieldPrefix + "_started":  false,
	}

	// Fire-and-forget DB write
	store.Send(defra.WriteOp{
		Collection: cfg.Collection,
		DocID:      docID,
		Document:   update,
		Op:         defra.OpUpdate,
		Source:     "PersistOpCompleteAsync:" + string(op),
	})
}

// PersistStructurePhase persists structure phase tracking data (phase + progress counters).
//
// Deprecated: Use PersistStructurePhaseAsync instead for better latency.
// This sync version blocks on DB write; async version fires and forgets.
func (b *BookState) PersistStructurePhase(ctx context.Context) error {
	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	total, extracted, polished, failed := b.GetStructureProgress()
	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      b.BookID,
		Document: map[string]any{
			"structure_phase":              b.GetStructurePhase(),
			"structure_chapters_total":     total,
			"structure_chapters_extracted": extracted,
			"structure_chapters_polished":  polished,
			"structure_polish_failed":      failed,
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return err
	}

	b.mu.Lock()
	b.trackCIDLocked("Book", b.BookID, result.CID)
	b.bookCID = result.CID
	b.mu.Unlock()

	return nil
}

// PersistStructurePhaseAsync fires and forgets structure phase tracking data.
// Memory is already updated by the caller, DB write is fire-and-forget.
func (b *BookState) PersistStructurePhaseAsync(ctx context.Context) {
	store := b.getStore(ctx)
	if store == nil {
		slog.Error("PersistStructurePhaseAsync: no store available", "book_id", b.BookID)
		return
	}

	total, extracted, polished, failed := b.GetStructureProgress()
	store.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      b.BookID,
		Document: map[string]any{
			"structure_phase":              b.GetStructurePhase(),
			"structure_chapters_total":     total,
			"structure_chapters_extracted": extracted,
			"structure_chapters_polished":  polished,
			"structure_polish_failed":      failed,
		},
		Op:     defra.OpUpdate,
		Source: "PersistStructurePhaseAsync",
	})
}

// PersistFinalizePhase persists finalize phase to ToC record.
// Returns error if no ToC document exists.
//
// Deprecated: Use PersistFinalizePhaseAsync instead for better latency.
// This sync version blocks on DB write; async version fires and forgets.
func (b *BookState) PersistFinalizePhase(ctx context.Context, phase string) (string, error) {
	tocDocID := b.TocDocID()
	if tocDocID == "" {
		return "", fmt.Errorf("cannot persist finalize phase: no ToC document exists for book %s", b.BookID)
	}

	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"finalize_phase": phase,
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return "", err
	}

	b.mu.Lock()
	b.finalizePhase = phase
	b.trackCIDLocked("ToC", tocDocID, result.CID)
	b.tocCID = result.CID
	b.mu.Unlock()

	return result.CID, nil
}

// PersistFinalizePhaseAsync fires and forgets finalize phase to ToC record.
// Updates memory immediately, fires DB write without blocking.
func (b *BookState) PersistFinalizePhaseAsync(ctx context.Context, phase string) {
	// Update memory first
	b.mu.Lock()
	b.finalizePhase = phase
	b.mu.Unlock()

	tocDocID := b.TocDocID()
	if tocDocID == "" {
		slog.Warn("PersistFinalizePhaseAsync: no ToC doc ID", "book_id", b.BookID)
		return
	}

	store := b.getStore(ctx)
	if store == nil {
		slog.Error("PersistFinalizePhaseAsync: no store available", "book_id", b.BookID)
		return
	}

	store.Send(defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"finalize_phase": phase,
		},
		Op:     defra.OpUpdate,
		Source: "PersistFinalizePhaseAsync",
	})
}

// PersistFinalizeProgress persists finalize progress counters to Book.
//
// Deprecated: Use PersistFinalizeProgressAsync instead for better latency.
// This sync version blocks on DB write; async version fires and forgets.
func (b *BookState) PersistFinalizeProgress(ctx context.Context) error {
	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	entriesComplete, entriesFound, gapsComplete, gapsFixes := b.GetFinalizeProgress()
	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      b.BookID,
		Document: map[string]any{
			"finalize_entries_total":    b.GetFinalizeEntriesTotalCount(),
			"finalize_entries_complete": entriesComplete,
			"finalize_entries_found":    entriesFound,
			"finalize_gaps_total":       b.GetFinalizeGapsTotalCount(),
			"finalize_gaps_complete":    gapsComplete,
			"finalize_gaps_fixes":       gapsFixes,
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return err
	}

	b.mu.Lock()
	b.trackCIDLocked("Book", b.BookID, result.CID)
	b.bookCID = result.CID
	b.mu.Unlock()

	return nil
}

// PersistFinalizeProgressAsync fires and forgets finalize progress counters to Book.
// Memory is already updated by the caller, DB write is fire-and-forget.
// Note: CID tracking is skipped for async writes - memory is authoritative during execution.
func (b *BookState) PersistFinalizeProgressAsync(ctx context.Context) {
	store := b.getStore(ctx)
	if store == nil {
		slog.Error("PersistFinalizeProgressAsync: no store available", "book_id", b.BookID)
		return
	}

	entriesComplete, entriesFound, gapsComplete, gapsFixes := b.GetFinalizeProgress()
	store.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      b.BookID,
		Document: map[string]any{
			"finalize_entries_total":    b.GetFinalizeEntriesTotalCount(),
			"finalize_entries_complete": entriesComplete,
			"finalize_entries_found":    entriesFound,
			"finalize_gaps_total":       b.GetFinalizeGapsTotalCount(),
			"finalize_gaps_complete":    gapsComplete,
			"finalize_gaps_fixes":       gapsFixes,
		},
		Op:     defra.OpUpdate,
		Source: "PersistFinalizeProgressAsync",
	})
}

// PersistTocLinkProgress persists toc link progress counters to Book.
//
// Deprecated: Use PersistTocLinkProgressAsync instead for better latency.
// This sync version blocks on DB write; async version fires and forgets.
func (b *BookState) PersistTocLinkProgress(ctx context.Context) error {
	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	total, done := b.GetTocLinkProgress()
	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      b.BookID,
		Document: map[string]any{
			"toc_link_entries_total": total,
			"toc_link_entries_done":  done,
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return err
	}

	b.mu.Lock()
	b.trackCIDLocked("Book", b.BookID, result.CID)
	b.bookCID = result.CID
	b.mu.Unlock()

	return nil
}

// PersistTocLinkProgressAsync fires and forgets toc link progress counters to Book.
// Memory is already updated by the caller, DB write is fire-and-forget.
// Note: CID tracking is skipped for async writes - memory is authoritative during execution.
func (b *BookState) PersistTocLinkProgressAsync(ctx context.Context) {
	store := b.getStore(ctx)
	if store == nil {
		slog.Error("PersistTocLinkProgressAsync: no store available", "book_id", b.BookID)
		return
	}

	total, done := b.GetTocLinkProgress()
	store.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      b.BookID,
		Document: map[string]any{
			"toc_link_entries_total": total,
			"toc_link_entries_done":  done,
		},
		Op:     defra.OpUpdate,
		Source: "PersistTocLinkProgressAsync",
	})
}

// --- Async (fire-and-forget) methods for latency-sensitive operations ---
// These methods update memory immediately and fire-and-forget the DB write.
// Use for stage transitions where memory consistency matters but DB can be eventually consistent.

// PersistOpStateAsync fires and forgets operation state to DB.
// Memory is already updated by the caller (via OpStart, etc.).
// This removes DB latency from the critical path between stages.
// Note: CID tracking is skipped for async writes - memory is authoritative during execution.
func (b *BookState) PersistOpStateAsync(ctx context.Context, op OpType) {
	cfg, ok := OpRegistry[op]
	if !ok {
		slog.Error("PersistOpStateAsync: unknown operation", "operation", op, "book_id", b.BookID)
		return
	}

	state := b.OpGetState(op)
	docID := cfg.DocIDSource(b)
	if docID == "" {
		// No document exists yet - this is expected before ToC record is created.
		// Log at debug level for visibility during debugging.
		slog.Debug("PersistOpStateAsync: skipped - no doc ID yet",
			"book_id", b.BookID,
			"operation", op,
			"collection", cfg.Collection)
		return
	}

	store := b.getStore(ctx)
	if store == nil {
		slog.Error("PersistOpStateAsync: no store available - check BookState initialization",
			"book_id", b.BookID, "operation", op)
		return
	}

	store.Send(defra.WriteOp{
		Collection: cfg.Collection,
		DocID:      docID,
		Document: map[string]any{
			cfg.FieldPrefix + "_started":  state.IsStarted(),
			cfg.FieldPrefix + "_complete": state.IsComplete(),
			cfg.FieldPrefix + "_failed":   state.IsFailed(),
			cfg.FieldPrefix + "_retries":  state.GetRetries(),
		},
		Op:     defra.OpUpdate,
		Source: "PersistOpStateAsync:" + string(op),
	})
}

// PersistTocFinderResultAsync saves ToC finder result with memory-first, async DB write.
// Updates memory state immediately, fires DB write without blocking.
// This removes DB latency from the toc_finder -> toc_extract transition.
// Note: CID tracking is skipped for async writes - memory is authoritative during execution.
func (b *BookState) PersistTocFinderResultAsync(ctx context.Context, found bool, startPage, endPage int, structureSummary any) {
	// Update memory state first (atomic, under lock)
	b.SetTocResult(found, startPage, endPage)

	tocDocID := b.TocDocID()
	if tocDocID == "" {
		slog.Warn("PersistTocFinderResultAsync: no ToC doc ID", "book_id", b.BookID)
		return
	}

	store := b.getStore(ctx)
	if store == nil {
		slog.Error("PersistTocFinderResultAsync: no store available - check BookState initialization",
			"book_id", b.BookID)
		return
	}

	update := map[string]any{
		"toc_found":       found,
		"finder_complete": true,
		"start_page":      startPage,
		"end_page":        endPage,
	}

	if structureSummary != nil {
		summaryJSON, err := json.Marshal(structureSummary)
		if err != nil {
			slog.Warn("PersistTocFinderResultAsync: failed to marshal structure_summary",
				"book_id", b.BookID, "error", err)
		} else {
			update["structure_summary"] = string(summaryJSON)
		}
	}

	// Fire-and-forget DB write
	store.Send(defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document:   update,
		Op:         defra.OpUpdate,
		Source:     "PersistTocFinderResultAsync",
	})
}
