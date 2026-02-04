package common

import (
	"context"
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

// PersistMetadataResult saves metadata to Book record and updates b.bookMetadata.
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

// PersistOpState persists operation state (started/complete/failed/retries) for any operation type.
// If the target document doesn't exist yet (e.g., ToC record not created), returns nil without error.
// This allows callers to call PersistOpState at any time without managing document lifecycle.
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

// PersistStructurePhase persists structure phase tracking data (phase + progress counters).
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

// PersistFinalizePhase persists finalize phase to ToC record.
// Returns error if no ToC document exists.
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

// PersistFinalizeProgress persists finalize progress counters to Book.
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

// PersistTocLinkProgress persists toc link progress counters to Book.
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
