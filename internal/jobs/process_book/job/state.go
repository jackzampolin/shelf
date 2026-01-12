package job

import (
	"context"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// GeneratePageWorkUnits creates work units for a page based on its current state.
// Must be called with j.Mu held.
func (j *Job) GeneratePageWorkUnits(ctx context.Context, pageNum int, state *PageState) []jobs.WorkUnit {
	var units []jobs.WorkUnit

	// Check if OCR is needed
	allOcrDone := true
	for _, provider := range j.Book.OcrProviders {
		if !state.OcrComplete(provider) {
			allOcrDone = false
			unit := j.CreateOcrWorkUnit(ctx, pageNum, provider)
			if unit != nil {
				units = append(units, *unit)
			}
		}
	}

	// If all OCR done but blend not done, create blend unit (thread-safe accessor)
	if allOcrDone && !state.IsBlendDone() {
		unit := j.CreateBlendWorkUnit(ctx, pageNum, state)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	// If blend done AND pattern analysis done but label not done, create label unit (thread-safe accessors)
	// Label now runs after pattern analysis to use pattern context for guidance
	if state.IsBlendDone() && j.Book.PatternAnalysis.IsComplete() && !state.IsLabelDone() {
		unit := j.CreateLabelWorkUnit(ctx, pageNum, state)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units
}

// MaybeStartBookOperations checks if we should trigger metadata/ToC operations.
// Must be called with j.mu held.
func (j *Job) MaybeStartBookOperations(ctx context.Context) []jobs.WorkUnit {
	labeledCount := j.CountLabeledPages()

	var units []jobs.WorkUnit

	// Start metadata extraction after threshold pages are labeled
	// IMPORTANT: Call Start() before creating work unit to prevent duplicate agents
	// if work unit creation has side effects (like creating agent logs)
	if labeledCount >= LabelThresholdForBookOps && j.Book.Metadata.CanStart() {
		if err := j.Book.Metadata.Start(); err == nil {
			unit := j.CreateMetadataWorkUnit(ctx)
			if unit != nil {
				if err := j.PersistMetadataState(ctx); err != nil {
					j.Book.Metadata.Reset() // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			} else {
				j.Book.Metadata.Reset() // No work unit created, allow retry
			}
		}
	}

	// Start ToC finder after first 30 pages have blend complete.
	// ToC finder only needs blended text (not labels), so no need to wait for labeling.
	// IMPORTANT: Call Start() before creating work unit to prevent duplicate agents
	if j.ConsecutiveFrontMatterComplete() && j.Book.TocFinder.CanStart() {
		if err := j.Book.TocFinder.Start(); err == nil {
			unit := j.CreateTocFinderWorkUnit(ctx)
			if unit != nil {
				if err := j.PersistTocFinderState(ctx); err != nil {
					j.Book.TocFinder.Reset() // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			} else {
				j.Book.TocFinder.Reset() // No work unit created, allow retry
			}
		}
	}

	// Start ToC extraction if finder is done and found a ToC
	// IMPORTANT: Call Start() before creating work unit to prevent duplicate agents
	if j.Book.TocFinder.IsDone() && j.Book.GetTocFound() && j.Book.TocExtract.CanStart() {
		logger := svcctx.LoggerFrom(ctx)
		tocStart, tocEnd := j.Book.GetTocPageRange()
		if logger != nil {
			logger.Info("attempting to create ToC extract work unit",
				"toc_start_page", tocStart,
				"toc_end_page", tocEnd,
				"toc_doc_id", j.TocDocID)
		}
		if err := j.Book.TocExtract.Start(); err == nil {
			unit := j.CreateTocExtractWorkUnit(ctx)
			if unit != nil {
				if err := j.PersistTocExtractState(ctx); err != nil {
					j.Book.TocExtract.Reset() // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			} else {
				j.Book.TocExtract.Reset() // No work unit created, allow retry
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
	if j.AllPagesBlendComplete() && j.Book.PatternAnalysis.CanStart() {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Info("all pages blend complete, starting pattern analysis",
				"book_id", j.Book.BookID,
				"total_pages", j.Book.TotalPages)
		}
		if err := j.Book.PatternAnalysis.Start(); err == nil {
			patternUnits := j.CreatePatternAnalysisWorkUnits(ctx)
			if len(patternUnits) > 0 {
				if err := j.PersistPatternAnalysisState(ctx); err != nil {
					j.Book.PatternAnalysis.Reset() // Rollback on failure
				} else {
					units = append(units, patternUnits...)
					if logger != nil {
						logger.Info("created pattern analysis work units",
							"count", len(patternUnits))
					}
				}
			} else {
				j.Book.PatternAnalysis.Reset() // No work unit created, allow retry
				if logger != nil {
					logger.Warn("failed to create pattern analysis work units")
				}
			}
		}
	}

	// Start ToC linking if extraction is done AND pattern analysis is done AND all pages are labeled
	// ToC linker needs page labels to find chapter start pages
	// IMPORTANT: Call Start() before creating work units to prevent duplicate agents
	if j.Book.TocExtract.IsDone() && j.Book.PatternAnalysis.IsComplete() && j.AllPagesComplete() && j.Book.TocLink.CanStart() {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Info("starting ToC link operation",
				"book_id", j.Book.BookID,
				"toc_doc_id", j.TocDocID)
		}
		if err := j.Book.TocLink.Start(); err == nil {
			linkUnits := j.CreateLinkTocWorkUnits(ctx)
			if len(linkUnits) > 0 {
				if err := j.PersistTocLinkState(ctx); err != nil {
					j.Book.TocLink.Reset() // Rollback on failure
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
				j.Book.TocLink.Complete()
				j.PersistTocLinkState(ctx)
				if logger != nil {
					logger.Info("no ToC entries to link - marking complete")
				}
			}
		}
	}

	// Start finalize-toc inline if linking is done and finalize not yet started
	if j.Book.TocLink.IsComplete() && j.Book.TocFinalize.CanStart() {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Info("link_toc complete, starting finalize-toc inline",
				"book_id", j.Book.BookID,
				"toc_doc_id", j.TocDocID)
		}
		finalizeUnits := j.StartFinalizeTocInline(ctx)
		units = append(units, finalizeUnits...)
	}

	return units
}

// CheckCompletion checks if the entire job is complete.
// A job is complete when all pages are labeled AND book-level operations
// are either complete or permanently failed.
func (j *Job) CheckCompletion(ctx context.Context) {
	// All pages must be labeled
	if !j.AllPagesComplete() {
		return
	}

	// Metadata must be complete or permanently failed
	if !j.Book.Metadata.IsDone() {
		return
	}

	// ToC finder must be complete or permanently failed
	if !j.Book.TocFinder.IsDone() {
		return
	}

	// If ToC was found, extraction must also be done
	if j.Book.GetTocFound() && !j.Book.TocExtract.IsDone() {
		return
	}

	// Pattern analysis must be complete or permanently failed
	if !j.Book.PatternAnalysis.IsDone() {
		return
	}

	// If ToC was extracted, linking must also be done
	if j.Book.TocExtract.IsDone() && !j.Book.TocLink.IsDone() {
		return
	}

	// If ToC was linked, finalize must also be done
	if j.Book.TocLink.IsComplete() && !j.Book.TocFinalize.IsDone() {
		return
	}

	// If finalize is complete, structure must also be done
	if j.Book.TocFinalize.IsComplete() && !j.Book.Structure.IsDone() {
		return
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
	return common.PersistMetadataState(ctx, j.Book.BookID, &j.Book.Metadata)
}

// PersistTocFinderState persists ToC finder state to DefraDB.
func (j *Job) PersistTocFinderState(ctx context.Context) error {
	return common.PersistTocFinderState(ctx, j.TocDocID, &j.Book.TocFinder)
}

// PersistTocExtractState persists ToC extract state to DefraDB.
func (j *Job) PersistTocExtractState(ctx context.Context) error {
	return common.PersistTocExtractState(ctx, j.TocDocID, &j.Book.TocExtract)
}

// PersistPatternAnalysisState persists pattern analysis state to DefraDB.
func (j *Job) PersistPatternAnalysisState(ctx context.Context) error {
	return common.PersistPatternAnalysisState(ctx, j.Book.BookID, &j.Book.PatternAnalysis)
}
