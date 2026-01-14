package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ResetOperation identifies an operation that can be reset.
type ResetOperation string

const (
	ResetMetadata        ResetOperation = "metadata"
	ResetTocFinder       ResetOperation = "toc_finder"
	ResetTocExtract      ResetOperation = "toc_extract"
	ResetPatternAnalysis ResetOperation = "pattern_analysis"
	ResetTocLink         ResetOperation = "toc_link"
	ResetTocFinalize     ResetOperation = "toc_finalize"
	ResetStructure       ResetOperation = "structure"
	ResetLabels          ResetOperation = "labels"
	ResetBlend           ResetOperation = "blend"
)

// ValidResetOperations lists all valid reset operations.
var ValidResetOperations = []ResetOperation{
	ResetMetadata,
	ResetTocFinder,
	ResetTocExtract,
	ResetPatternAnalysis,
	ResetTocLink,
	ResetTocFinalize,
	ResetStructure,
	ResetLabels,
	ResetBlend,
}

// IsValidResetOperation checks if an operation name is valid.
func IsValidResetOperation(op string) bool {
	for _, valid := range ValidResetOperations {
		if string(valid) == op {
			return true
		}
	}
	return false
}

// ResetFrom resets an operation and all its downstream dependencies.
// This enables re-running specific stages of the pipeline.
//
// Cascade dependencies:
//   - metadata        -> (none)
//   - toc_finder      -> toc_extract, toc_link, toc_finalize, structure
//   - toc_extract     -> toc_link, toc_finalize, structure
//   - pattern_analysis -> labels (all pages), toc_link, toc_finalize, structure
//   - toc_link        -> toc_finalize, structure
//   - toc_finalize    -> structure
//   - structure       -> (none)
//   - labels          -> toc_link, toc_finalize, structure
//   - blend           -> labels, pattern_analysis, (cascade from pattern_analysis)
func ResetFrom(ctx context.Context, book *BookState, tocDocID string, op ResetOperation) error {
	// Validate IDs to prevent GraphQL injection
	if err := defra.ValidateID(book.BookID); err != nil {
		return fmt.Errorf("invalid book ID: %w", err)
	}
	if tocDocID != "" {
		if err := defra.ValidateID(tocDocID); err != nil {
			return fmt.Errorf("invalid ToC doc ID: %w", err)
		}
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("resetting operation with cascade", "operation", op, "book_id", book.BookID)
	}

	switch op {
	case ResetMetadata:
		return resetMetadata(ctx, book)

	case ResetTocFinder:
		if err := resetTocFinder(ctx, book, tocDocID); err != nil {
			return err
		}
		return ResetFrom(ctx, book, tocDocID, ResetTocExtract)

	case ResetTocExtract:
		if err := resetTocExtract(ctx, book, tocDocID); err != nil {
			return err
		}
		return ResetFrom(ctx, book, tocDocID, ResetTocLink)

	case ResetPatternAnalysis:
		if err := resetPatternAnalysis(ctx, book); err != nil {
			return err
		}
		// Pattern analysis reset requires resetting all labels
		if err := resetAllLabels(ctx, book); err != nil {
			return err
		}
		return ResetFrom(ctx, book, tocDocID, ResetTocLink)

	case ResetTocLink:
		if err := resetTocLink(ctx, book, tocDocID); err != nil {
			return err
		}
		return ResetFrom(ctx, book, tocDocID, ResetTocFinalize)

	case ResetTocFinalize:
		if err := resetTocFinalize(ctx, book, tocDocID); err != nil {
			return err
		}
		return ResetFrom(ctx, book, tocDocID, ResetStructure)

	case ResetStructure:
		return resetStructure(ctx, book)

	case ResetLabels:
		if err := resetAllLabels(ctx, book); err != nil {
			return err
		}
		return ResetFrom(ctx, book, tocDocID, ResetTocLink)

	case ResetBlend:
		if err := resetAllBlends(ctx, book); err != nil {
			return err
		}
		// Blend reset cascades through labels and pattern analysis
		if err := resetAllLabels(ctx, book); err != nil {
			return err
		}
		if err := resetPatternAnalysis(ctx, book); err != nil {
			return err
		}
		return ResetFrom(ctx, book, tocDocID, ResetTocLink)

	default:
		return fmt.Errorf("unknown reset operation: %s", op)
	}
}

// resetMetadata resets metadata extraction state.
func resetMetadata(ctx context.Context, book *BookState) error {
	book.MetadataReset()

	// Clear agent state for metadata (if any) - both memory and DB
	book.ClearAgentStates("metadata")
	if err := DeleteAgentStatesForType(ctx, book.BookID, "metadata"); err != nil {
		return fmt.Errorf("failed to delete metadata agent states: %w", err)
	}

	metadataState := book.GetMetadataState()
	return PersistMetadataState(ctx, book.BookID, &metadataState)
}

// resetTocFinder resets ToC finder state.
func resetTocFinder(ctx context.Context, book *BookState, tocDocID string) error {
	book.TocFinderReset()
	book.SetTocFound(false)
	book.SetTocPageRange(0, 0)

	// Clear agent state - both memory and DB
	book.ClearAgentStates("toc_finder")
	if err := DeleteAgentStatesForType(ctx, book.BookID, "toc_finder"); err != nil {
		return fmt.Errorf("failed to delete toc_finder agent states: %w", err)
	}

	if tocDocID == "" {
		return nil
	}

	// Reset ToC record - use sync to ensure reset completes before proceeding
	return SendToSinkSync(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"toc_found":        false,
			"finder_started":   false,
			"finder_complete":  false,
			"finder_failed":    false,
			"finder_retries":   0,
			"start_page":       nil,
			"end_page":         nil,
		},
		Op: defra.OpUpdate,
	})
}

// resetTocExtract resets ToC extraction state.
func resetTocExtract(ctx context.Context, book *BookState, tocDocID string) error {
	book.TocExtractReset()
	book.SetTocEntries(nil)

	// Clear agent state - both memory and DB
	book.ClearAgentStates("toc_extract")
	if err := DeleteAgentStatesForType(ctx, book.BookID, "toc_extract"); err != nil {
		return fmt.Errorf("failed to delete toc_extract agent states: %w", err)
	}

	if tocDocID == "" {
		return nil
	}

	// Delete all ToC entries for this ToC
	if err := deleteTocEntries(ctx, tocDocID); err != nil {
		return err
	}

	// Reset ToC record - use sync to ensure reset completes before proceeding
	return SendToSinkSync(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"extract_started":  false,
			"extract_complete": false,
			"extract_failed":   false,
			"extract_retries":  0,
		},
		Op: defra.OpUpdate,
	})
}

// resetPatternAnalysis resets pattern analysis state.
func resetPatternAnalysis(ctx context.Context, book *BookState) error {
	book.PatternAnalysisReset()
	book.SetPatternAnalysisResult(nil)
	book.SetPageNumberPattern(nil)
	book.SetChapterPatterns(nil)

	// Clear agent state - both memory and DB
	book.ClearAgentStates("pattern_analysis")
	if err := DeleteAgentStatesForType(ctx, book.BookID, "pattern_analysis"); err != nil {
		return fmt.Errorf("failed to delete pattern_analysis agent states: %w", err)
	}

	// Clear pattern analysis JSON from book (sync to ensure it completes)
	return SendToSinkSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      book.BookID,
		Document: map[string]any{
			"pattern_analysis_started":   false,
			"pattern_analysis_complete":  false,
			"pattern_analysis_failed":    false,
			"pattern_analysis_retries":   0,
			"page_pattern_analysis_json": nil,
		},
		Op: defra.OpUpdate,
	})
}

// resetTocLink resets ToC linking state.
func resetTocLink(ctx context.Context, book *BookState, tocDocID string) error {
	book.TocLinkReset()

	// Clear agent state for all link agents - both memory and DB
	book.ClearAgentStates(AgentTypeTocEntryFinder)
	book.ClearAgentStates(AgentTypeChapterFinder)
	if err := DeleteAgentStatesForType(ctx, book.BookID, AgentTypeTocEntryFinder); err != nil {
		return fmt.Errorf("failed to delete %s agent states: %w", AgentTypeTocEntryFinder, err)
	}
	if err := DeleteAgentStatesForType(ctx, book.BookID, AgentTypeChapterFinder); err != nil {
		return fmt.Errorf("failed to delete %s agent states: %w", AgentTypeChapterFinder, err)
	}

	// Clear cached LinkedEntries since links are being cleared
	book.SetLinkedEntries(nil)

	if tocDocID == "" {
		return nil
	}

	// Clear actual_page links from all ToC entries
	if err := clearTocEntryLinks(ctx, tocDocID); err != nil {
		return err
	}

	// Reset ToC record - use sync to ensure reset completes before proceeding
	return SendToSinkSync(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"link_started":  false,
			"link_complete": false,
			"link_failed":   false,
			"link_retries":  0,
		},
		Op: defra.OpUpdate,
	})
}

// resetTocFinalize resets ToC finalization state.
func resetTocFinalize(ctx context.Context, book *BookState, tocDocID string) error {
	book.TocFinalizeReset()

	// Clear in-memory finalize state
	book.SetFinalizePhase("")
	book.SetFinalizePatternResult(nil)
	book.SetEntriesToFind(nil)
	book.SetFinalizeGaps(nil)
	book.SetFinalizeProgress(0, 0, 0, 0)

	// Clear agent states for finalize agents - both memory and DB
	book.ClearAgentStates(AgentTypeGapInvestigator)
	book.ClearAgentStates("discover_entry") // Not in common constants - used by discover phase
	if err := DeleteAgentStatesForType(ctx, book.BookID, AgentTypeGapInvestigator); err != nil {
		return fmt.Errorf("failed to delete %s agent states: %w", AgentTypeGapInvestigator, err)
	}
	if err := DeleteAgentStatesForType(ctx, book.BookID, "discover_entry"); err != nil {
		return fmt.Errorf("failed to delete discover_entry agent states: %w", err)
	}

	if tocDocID == "" {
		return nil
	}

	// Reset ToC record - use sync to ensure reset completes before proceeding
	return SendToSinkSync(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"finalize_started":  false,
			"finalize_complete": false,
			"finalize_failed":   false,
			"finalize_retries":  0,
		},
		Op: defra.OpUpdate,
	})
}

// resetStructure resets structure extraction state.
func resetStructure(ctx context.Context, book *BookState) error {
	book.StructureReset()
	book.SetStructurePhase("")
	book.SetStructureProgress(0, 0, 0, 0)

	// Clear in-memory structure state
	book.SetStructureChapters(nil)
	book.SetStructureClassifications(nil)
	book.SetStructureClassifyPending(false)

	// Clear agent state - both memory and DB
	book.ClearAgentStates("structure")
	book.ClearAgentStates("polish_chapter")
	if err := DeleteAgentStatesForType(ctx, book.BookID, "structure"); err != nil {
		return fmt.Errorf("failed to delete structure agent states: %w", err)
	}
	if err := DeleteAgentStatesForType(ctx, book.BookID, "polish_chapter"); err != nil {
		return fmt.Errorf("failed to delete polish_chapter agent states: %w", err)
	}

	// Delete all chapters for this book
	if err := deleteChapters(ctx, book.BookID); err != nil {
		return err
	}

	// Reset book record - use sync to ensure reset completes before proceeding
	return SendToSinkSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      book.BookID,
		Document: map[string]any{
			"structure_started":            false,
			"structure_complete":           false,
			"structure_failed":             false,
			"structure_retries":            0,
			"structure_phase":              nil,
			"structure_chapters_total":     0,
			"structure_chapters_extracted": 0,
			"structure_chapters_polished":  0,
			"structure_polish_failed":      0,
			"total_chapters":               0,
			"total_paragraphs":             0,
			"total_words":                  0,
		},
		Op: defra.OpUpdate,
	})
}

// resetAllLabels resets label_complete for all pages.
func resetAllLabels(ctx context.Context, book *BookState) error {
	logger := svcctx.LoggerFrom(ctx)
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Reset in-memory state
	book.ForEachPage(func(pageNum int, state *PageState) {
		state.SetLabelDone(false)
	})

	// Reset in DB - query all pages and update
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, label_complete: {_eq: true}}) {
			_docID
		}
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query pages for label reset: %w", err)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok || len(pages) == 0 {
		return nil
	}

	var resetCount, skipCount, failCount int
	for _, p := range pages {
		page, ok := p.(map[string]any)
		if !ok {
			skipCount++
			if logger != nil {
				logger.Warn("unexpected page data type during label reset", "type", fmt.Sprintf("%T", p))
			}
			continue
		}
		docID, ok := page["_docID"].(string)
		if !ok || docID == "" {
			skipCount++
			if logger != nil {
				logger.Warn("missing or invalid _docID during label reset", "page_data", page)
			}
			continue
		}
		// Use sync write to ensure reset completes
		_, err := sink.SendSync(ctx, defra.WriteOp{
			Collection: "Page",
			DocID:      docID,
			Document: map[string]any{
				"label_complete":    false,
				"page_number_label": nil,
				"running_header":    nil,
			},
			Op: defra.OpUpdate,
		})
		if err != nil {
			failCount++
			if logger != nil {
				logger.Error("failed to reset label for page", "doc_id", docID, "error", err)
			}
			continue
		}
		resetCount++
	}

	if logger != nil {
		logger.Info("reset labels completed", "reset_count", resetCount, "skipped", skipCount, "failed", failCount, "book_id", book.BookID)
	}

	if skipCount > 0 || failCount > 0 {
		return fmt.Errorf("label reset had issues: skipped=%d, failed=%d", skipCount, failCount)
	}
	return nil
}

// resetAllBlends resets blend_complete for all pages.
func resetAllBlends(ctx context.Context, book *BookState) error {
	logger := svcctx.LoggerFrom(ctx)
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Reset in-memory state
	book.ForEachPage(func(pageNum int, state *PageState) {
		state.SetBlendDone(false)
		state.SetBlendResult("")
	})

	// Reset in DB - query all pages and update
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, blend_complete: {_eq: true}}) {
			_docID
		}
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query pages for blend reset: %w", err)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok || len(pages) == 0 {
		return nil
	}

	var resetCount, skipCount, failCount int
	for _, p := range pages {
		page, ok := p.(map[string]any)
		if !ok {
			skipCount++
			if logger != nil {
				logger.Warn("unexpected page data type during blend reset", "type", fmt.Sprintf("%T", p))
			}
			continue
		}
		docID, ok := page["_docID"].(string)
		if !ok || docID == "" {
			skipCount++
			if logger != nil {
				logger.Warn("missing or invalid _docID during blend reset", "page_data", page)
			}
			continue
		}
		// Use sync write to ensure reset completes
		_, err := sink.SendSync(ctx, defra.WriteOp{
			Collection: "Page",
			DocID:      docID,
			Document: map[string]any{
				"blend_complete": false,
				"blend_markdown": nil,
				"headings":       nil,
			},
			Op: defra.OpUpdate,
		})
		if err != nil {
			failCount++
			if logger != nil {
				logger.Error("failed to reset blend for page", "doc_id", docID, "error", err)
			}
			continue
		}
		resetCount++
	}

	if logger != nil {
		logger.Info("reset blends completed", "reset_count", resetCount, "skipped", skipCount, "failed", failCount, "book_id", book.BookID)
	}

	if skipCount > 0 || failCount > 0 {
		return fmt.Errorf("blend reset had issues: skipped=%d, failed=%d", skipCount, failCount)
	}
	return nil
}

// deleteTocEntries deletes all ToC entries for a ToC.
func deleteTocEntries(ctx context.Context, tocDocID string) error {
	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		TocEntry(filter: {toc_id: {_eq: "%s"}}) {
			_docID
		}
	}`, tocDocID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query ToC entries for deletion: %w", err)
	}

	entries, ok := resp.Data["TocEntry"].([]any)
	if !ok || len(entries) == 0 {
		return nil
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	var deleteCount, skipCount, failCount int
	for _, e := range entries {
		entry, ok := e.(map[string]any)
		if !ok {
			skipCount++
			if logger != nil {
				logger.Warn("unexpected ToC entry data type during deletion", "type", fmt.Sprintf("%T", e))
			}
			continue
		}
		docID, ok := entry["_docID"].(string)
		if !ok || docID == "" {
			skipCount++
			if logger != nil {
				logger.Warn("missing or invalid _docID during ToC entry deletion", "entry_data", entry)
			}
			continue
		}
		// Use sync write to ensure deletion completes
		_, err := sink.SendSync(ctx, defra.WriteOp{
			Collection: "TocEntry",
			DocID:      docID,
			Op:         defra.OpDelete,
		})
		if err != nil {
			failCount++
			if logger != nil {
				logger.Error("failed to delete ToC entry", "doc_id", docID, "error", err)
			}
			continue
		}
		deleteCount++
	}

	if logger != nil {
		logger.Info("ToC entries deletion completed", "delete_count", deleteCount, "skipped", skipCount, "failed", failCount, "toc_id", tocDocID)
	}

	if skipCount > 0 || failCount > 0 {
		return fmt.Errorf("ToC entry deletion had issues: skipped=%d, failed=%d", skipCount, failCount)
	}
	return nil
}

// clearTocEntryLinks clears actual_page links from ToC entries.
func clearTocEntryLinks(ctx context.Context, tocDocID string) error {
	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		TocEntry(filter: {toc_id: {_eq: "%s"}}) {
			_docID
		}
	}`, tocDocID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query ToC entries for link clearing: %w", err)
	}

	entries, ok := resp.Data["TocEntry"].([]any)
	if !ok || len(entries) == 0 {
		return nil
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	var clearCount, skipCount, failCount int
	for _, e := range entries {
		entry, ok := e.(map[string]any)
		if !ok {
			skipCount++
			if logger != nil {
				logger.Warn("unexpected ToC entry data type during link clearing", "type", fmt.Sprintf("%T", e))
			}
			continue
		}
		docID, ok := entry["_docID"].(string)
		if !ok || docID == "" {
			skipCount++
			if logger != nil {
				logger.Warn("missing or invalid _docID during ToC entry link clearing", "entry_data", entry)
			}
			continue
		}
		// Use sync write to ensure link clearing completes
		_, err := sink.SendSync(ctx, defra.WriteOp{
			Collection: "TocEntry",
			DocID:      docID,
			Document: map[string]any{
				"actual_page_id": nil,
			},
			Op: defra.OpUpdate,
		})
		if err != nil {
			failCount++
			if logger != nil {
				logger.Error("failed to clear ToC entry link", "doc_id", docID, "error", err)
			}
			continue
		}
		clearCount++
	}

	if logger != nil {
		logger.Info("ToC entry links clearing completed", "clear_count", clearCount, "skipped", skipCount, "failed", failCount, "toc_id", tocDocID)
	}

	if skipCount > 0 || failCount > 0 {
		return fmt.Errorf("ToC entry link clearing had issues: skipped=%d, failed=%d", skipCount, failCount)
	}
	return nil
}

// deleteChapters deletes all chapters for a book.
func deleteChapters(ctx context.Context, bookID string) error {
	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Chapter(filter: {book_id: {_eq: "%s"}}) {
			_docID
		}
	}`, bookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query chapters for deletion: %w", err)
	}

	chapters, ok := resp.Data["Chapter"].([]any)
	if !ok || len(chapters) == 0 {
		return nil
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	var deleteCount, skipCount, failCount int
	for _, c := range chapters {
		chapter, ok := c.(map[string]any)
		if !ok {
			skipCount++
			if logger != nil {
				logger.Warn("unexpected chapter data type during deletion", "type", fmt.Sprintf("%T", c))
			}
			continue
		}
		docID, ok := chapter["_docID"].(string)
		if !ok || docID == "" {
			skipCount++
			if logger != nil {
				logger.Warn("missing or invalid _docID during chapter deletion", "chapter_data", chapter)
			}
			continue
		}
		// Use sync write to ensure deletion completes
		_, err := sink.SendSync(ctx, defra.WriteOp{
			Collection: "Chapter",
			DocID:      docID,
			Op:         defra.OpDelete,
		})
		if err != nil {
			failCount++
			if logger != nil {
				logger.Error("failed to delete chapter", "doc_id", docID, "error", err)
			}
			continue
		}
		deleteCount++
	}

	if logger != nil {
		logger.Info("chapter deletion completed", "delete_count", deleteCount, "skipped", skipCount, "failed", failCount, "book_id", bookID)
	}

	if skipCount > 0 || failCount > 0 {
		return fmt.Errorf("chapter deletion had issues: skipped=%d, failed=%d", skipCount, failCount)
	}
	return nil
}
