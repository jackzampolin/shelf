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
		unit := j.CreateBlendWorkUnit(pageNum, state)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	// If blend done but label not done, create label unit (thread-safe accessors)
	if state.IsBlendDone() && !state.IsLabelDone() {
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
	if labeledCount >= LabelThresholdForBookOps && j.Book.Metadata.CanStart() {
		unit := j.CreateMetadataWorkUnit(ctx)
		if unit != nil {
			if err := j.Book.Metadata.Start(); err == nil {
				if err := j.PersistMetadataState(ctx); err != nil {
					j.Book.Metadata.Reset() // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			}
		}
	}

	// Start ToC finder after threshold pages are labeled AND first 30 pages have OCR.
	// Consecutive check ensures pages 1-30 all have blend_complete before ToC finder starts,
	// since ToC is typically in the first 20-30 pages.
	if labeledCount >= LabelThresholdForBookOps && j.ConsecutiveFrontMatterComplete() && j.Book.TocFinder.CanStart() {
		unit := j.CreateTocFinderWorkUnit(ctx)
		if unit != nil {
			if err := j.Book.TocFinder.Start(); err == nil {
				if err := j.PersistTocFinderState(ctx); err != nil {
					j.Book.TocFinder.Reset() // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			}
		}
	}

	// Start ToC extraction if finder is done and found a ToC
	if j.Book.TocFinder.IsDone() && j.Book.GetTocFound() && j.Book.TocExtract.CanStart() {
		logger := svcctx.LoggerFrom(ctx)
		tocStart, tocEnd := j.Book.GetTocPageRange()
		if logger != nil {
			logger.Info("attempting to create ToC extract work unit",
				"toc_start_page", tocStart,
				"toc_end_page", tocEnd,
				"toc_doc_id", j.TocDocID)
		}
		unit := j.CreateTocExtractWorkUnit(ctx)
		if unit != nil {
			if err := j.Book.TocExtract.Start(); err == nil {
				if err := j.PersistTocExtractState(ctx); err != nil {
					j.Book.TocExtract.Reset() // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			}
		} else if logger != nil {
			logger.Warn("failed to create ToC extract work unit",
				"toc_start_page", tocStart,
				"toc_end_page", tocEnd)
		}
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
