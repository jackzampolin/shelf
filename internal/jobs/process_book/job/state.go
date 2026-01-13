package job

import (
	"context"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// GeneratePageWorkUnits creates work units for a page based on its current state.
// Must be called with j.Mu held.
// Respects pipeline stage toggles (EnableOCR, EnableBlend, EnableLabel).
func (j *Job) GeneratePageWorkUnits(ctx context.Context, pageNum int, state *PageState) []jobs.WorkUnit {
	var units []jobs.WorkUnit

	// Check if OCR is needed (only if enabled)
	allOcrDone := true
	if j.Book.EnableOCR {
		for _, provider := range j.Book.OcrProviders {
			if !state.OcrComplete(provider) {
				allOcrDone = false
				unit := j.CreateOcrWorkUnit(ctx, pageNum, provider)
				if unit != nil {
					units = append(units, *unit)
				}
			}
		}
	}

	// If all OCR done but blend not done, create blend unit (thread-safe accessor)
	// Only if blend is enabled
	if j.Book.EnableBlend && allOcrDone && !state.IsBlendDone() {
		unit := j.CreateBlendWorkUnit(ctx, pageNum, state)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	// If blend done AND pattern analysis done but label not done, create label unit (thread-safe accessors)
	// Label now runs after pattern analysis to use pattern context for guidance
	// Only if label is enabled
	// If pattern analysis is disabled, skip waiting for it
	patternDone := !j.Book.EnablePatternAnalysis || j.Book.PatternAnalysisIsComplete()
	if j.Book.EnableLabel && state.IsBlendDone() && patternDone && !state.IsLabelDone() {
		unit := j.CreateLabelWorkUnit(ctx, pageNum, state)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units
}

// MaybeStartBookOperations checks if we should trigger metadata/ToC operations.
// Must be called with j.mu held.
// Respects pipeline stage toggles for each operation.
func (j *Job) MaybeStartBookOperations(ctx context.Context) []jobs.WorkUnit {
	blendedCount := j.CountBlendedPages()

	var units []jobs.WorkUnit

	// Start metadata extraction after threshold pages are blended
	// Metadata only needs blended text (not labels), so it can start early
	// IMPORTANT: Call Start() before creating work unit to prevent duplicate agents
	// if work unit creation has side effects (like creating agent logs)
	if j.Book.EnableMetadata && blendedCount >= BlendThresholdForMetadata && j.Book.MetadataCanStart() {
		if err := j.Book.MetadataStart(); err == nil {
			unit := j.CreateMetadataWorkUnit(ctx)
			if unit != nil {
				if err := j.PersistMetadataState(ctx); err != nil {
					j.Book.MetadataReset() // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			} else {
				j.Book.MetadataReset() // No work unit created, allow retry
			}
		}
	}

	// Start ToC finder after first 30 pages have blend complete.
	// ToC finder only needs blended text (not labels), so no need to wait for labeling.
	// IMPORTANT: Call Start() before creating work unit to prevent duplicate agents
	if j.Book.EnableTocFinder && j.ConsecutiveFrontMatterComplete() && j.Book.TocFinderCanStart() {
		if err := j.Book.TocFinderStart(); err == nil {
			unit := j.CreateTocFinderWorkUnit(ctx)
			if unit != nil {
				if err := j.PersistTocFinderState(ctx); err != nil {
					j.Book.TocFinderReset() // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			} else {
				j.Book.TocFinderReset() // No work unit created, allow retry
			}
		}
	}

	// Start ToC extraction if finder is done and found a ToC
	// IMPORTANT: Call Start() before creating work unit to prevent duplicate agents
	if j.Book.EnableTocExtract && j.Book.TocFinderIsDone() && j.Book.GetTocFound() && j.Book.TocExtractCanStart() {
		logger := svcctx.LoggerFrom(ctx)
		tocStart, tocEnd := j.Book.GetTocPageRange()
		if logger != nil {
			logger.Info("attempting to create ToC extract work unit",
				"toc_start_page", tocStart,
				"toc_end_page", tocEnd,
				"toc_doc_id", j.TocDocID)
		}
		if err := j.Book.TocExtractStart(); err == nil {
			unit := j.CreateTocExtractWorkUnit(ctx)
			if unit != nil {
				if err := j.PersistTocExtractState(ctx); err != nil {
					j.Book.TocExtractReset() // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			} else {
				j.Book.TocExtractReset() // No work unit created, allow retry
				if logger != nil {
					logger.Warn("failed to create ToC extract work unit",
						"toc_start_page", tocStart,
						"toc_end_page", tocEnd)
				}
			}
		}
	}

	// Start pattern analysis after ALL pages have blend complete
	// Pattern analysis needs blended text from ALL pages for cross-page analysis
	// IMPORTANT: Call Start() before creating work units to prevent duplicate agents
	if j.Book.EnablePatternAnalysis && j.AllPagesBlendComplete() && j.Book.PatternAnalysisCanStart() {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Info("all pages blend complete, starting pattern analysis",
				"book_id", j.Book.BookID,
				"total_pages", j.Book.TotalPages)
		}
		if err := j.Book.PatternAnalysisStart(); err == nil {
			patternUnits := j.CreatePatternAnalysisWorkUnits(ctx)
			if len(patternUnits) > 0 {
				if err := j.PersistPatternAnalysisState(ctx); err != nil {
					j.Book.PatternAnalysisReset() // Rollback on failure
				} else {
					units = append(units, patternUnits...)
					if logger != nil {
						logger.Info("created pattern analysis work units",
							"count", len(patternUnits))
					}
				}
			} else {
				j.Book.PatternAnalysisReset() // No work unit created, allow retry
				if logger != nil {
					logger.Warn("failed to create pattern analysis work units")
				}
			}
		}
	}

	// Start ToC linking if extraction is done AND pattern analysis is done (or disabled) AND all pages are labeled (or label disabled)
	// ToC linker needs page labels to find chapter start pages
	// IMPORTANT: Call Start() before creating work units to prevent duplicate agents
	patternReady := !j.Book.EnablePatternAnalysis || j.Book.PatternAnalysisIsComplete()
	labelReady := !j.Book.EnableLabel || j.AllPagesComplete()
	if j.Book.EnableTocLink && j.Book.TocExtractIsDone() && patternReady && labelReady && j.Book.TocLinkCanStart() {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Info("starting ToC link operation",
				"book_id", j.Book.BookID,
				"toc_doc_id", j.TocDocID)
		}
		if err := j.Book.TocLinkStart(); err == nil {
			linkUnits := j.CreateLinkTocWorkUnits(ctx)
			if len(linkUnits) > 0 {
				if err := j.PersistTocLinkState(ctx); err != nil {
					j.Book.TocLinkReset() // Rollback on failure
				} else {
					units = append(units, linkUnits...)
					if logger != nil {
						logger.Info("created link toc work units",
							"count", len(linkUnits),
							"entries", len(j.LinkTocEntries))
					}
				}
			} else {
				// No entries to link - mark as complete
				j.Book.TocLinkComplete()
				j.PersistTocLinkState(ctx)
				if logger != nil {
					logger.Info("no ToC entries to link - marking complete")
				}
			}
		}
	}

	// Start finalize-toc inline if linking is done and finalize not yet started
	if j.Book.EnableTocFinalize && j.Book.TocLinkIsComplete() && j.Book.TocFinalizeCanStart() {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Info("link_toc complete, starting finalize-toc inline",
				"book_id", j.Book.BookID,
				"toc_doc_id", j.TocDocID)
		}
		finalizeUnits := j.StartFinalizeTocInline(ctx)
		units = append(units, finalizeUnits...)
	}

	// Start structure if finalize is complete and structure not yet started
	// This handles both: (1) finalize just completed, (2) crash recovery reset structure
	if j.Book.EnableStructure && j.Book.TocFinalizeIsComplete() && j.Book.StructureCanStart() {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Info("finalize complete, starting structure inline",
				"book_id", j.Book.BookID)
		}
		structureUnits := j.MaybeStartStructureInline(ctx)
		units = append(units, structureUnits...)
	}

	return units
}

// CheckCompletion checks if the entire job is complete.
// A job is complete when all enabled pages stages are done AND enabled book-level operations
// are either complete or permanently failed.
// Disabled stages are skipped in the completion check.
func (j *Job) CheckCompletion(ctx context.Context) {
	// All pages must complete enabled page-level stages
	// For label-enabled: all pages must be labeled
	// For blend-only: all pages must be blended
	// For OCR-only: all pages must have OCR
	if j.Book.EnableLabel {
		if !j.AllPagesComplete() {
			return
		}
	} else if j.Book.EnableBlend {
		if !j.AllPagesBlendComplete() {
			return
		}
	} else if j.Book.EnableOCR {
		// For OCR-only, all pages need OCR complete
		ocrComplete := true
		j.Book.ForEachPage(func(pageNum int, state *PageState) {
			for _, provider := range j.Book.OcrProviders {
				if !state.OcrComplete(provider) {
					ocrComplete = false
					return
				}
			}
		})
		if !ocrComplete {
			return
		}
	}

	// Metadata must be complete or permanently failed (if enabled)
	if j.Book.EnableMetadata && !j.Book.MetadataIsDone() {
		return
	}

	// ToC finder must be complete or permanently failed (if enabled)
	if j.Book.EnableTocFinder && !j.Book.TocFinderIsDone() {
		return
	}

	// ToC extraction depends on finder finding a ToC
	// If extraction enabled but finder disabled/didn't find ToC, extraction is skipped
	// Note: Config validation should enforce EnableTocFinder when EnableTocExtract is true
	if j.Book.EnableTocExtract {
		if !j.Book.EnableTocFinder {
			// Finder disabled means no ToC can be found, so extraction is N/A
			// Log this edge case for debugging
			logger := svcctx.LoggerFrom(ctx)
			if logger != nil {
				logger.Debug("ToC extract enabled but finder disabled - extraction skipped")
			}
		} else if j.Book.GetTocFound() && !j.Book.TocExtractIsDone() {
			return
		}
	}

	// Pattern analysis must be complete or permanently failed (if enabled)
	if j.Book.EnablePatternAnalysis && !j.Book.PatternAnalysisIsDone() {
		return
	}

	// ToC linking depends on extraction being complete
	// If link enabled but extract disabled/not done, linking is skipped
	if j.Book.EnableTocLink {
		if !j.Book.EnableTocExtract {
			logger := svcctx.LoggerFrom(ctx)
			if logger != nil {
				logger.Debug("ToC link enabled but extract disabled - linking skipped")
			}
		} else if j.Book.TocExtractIsDone() && !j.Book.TocLinkIsDone() {
			return
		}
	}

	// ToC finalize depends on linking being complete
	if j.Book.EnableTocFinalize {
		if !j.Book.EnableTocLink {
			logger := svcctx.LoggerFrom(ctx)
			if logger != nil {
				logger.Debug("ToC finalize enabled but link disabled - finalize skipped")
			}
		} else if j.Book.TocLinkIsComplete() && !j.Book.TocFinalizeIsDone() {
			return
		}
	}

	// Structure depends on finalize being complete
	if j.Book.EnableStructure {
		if !j.Book.EnableTocFinalize {
			logger := svcctx.LoggerFrom(ctx)
			if logger != nil {
				logger.Debug("Structure enabled but finalize disabled - structure skipped")
			}
		} else if j.Book.TocFinalizeIsComplete() && !j.Book.StructureIsDone() {
			return
		}
	}

	j.IsDone = true

	// Persist the complete status to DefraDB
	j.PersistBookStatus(ctx, BookStatusComplete)
}

// PersistBookStatus persists book status to DefraDB.
func (j *Job) PersistBookStatus(ctx context.Context, status BookStatus) error {
	return common.PersistBookStatus(ctx, j.Book.BookID, string(status))
}

// PersistMetadataState persists metadata state to DefraDB.
func (j *Job) PersistMetadataState(ctx context.Context) error {
	metadataState := j.Book.GetMetadataState()
	return common.PersistMetadataState(ctx, j.Book.BookID, &metadataState)
}

// PersistTocFinderState persists ToC finder state to DefraDB.
func (j *Job) PersistTocFinderState(ctx context.Context) error {
	tocFinderState := j.Book.GetTocFinderState()
	return common.PersistTocFinderState(ctx, j.TocDocID, &tocFinderState)
}

// PersistTocExtractState persists ToC extract state to DefraDB.
func (j *Job) PersistTocExtractState(ctx context.Context) error {
	tocExtractState := j.Book.GetTocExtractState()
	return common.PersistTocExtractState(ctx, j.TocDocID, &tocExtractState)
}

// PersistPatternAnalysisState persists pattern analysis state to DefraDB.
func (j *Job) PersistPatternAnalysisState(ctx context.Context) error {
	patternAnalysisState := j.Book.GetPatternAnalysisState()
	return common.PersistPatternAnalysisState(ctx, j.Book.BookID, &patternAnalysisState)
}
