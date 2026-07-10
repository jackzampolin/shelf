package job

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// MaxStructureRetries is the maximum number of retries for structure operations.
const MaxStructureRetries = 3

// Structure phase constants (aligned with common_structure)
const (
	StructPhaseBuild    = "build"
	StructPhaseExtract  = "extract"
	StructPhaseClassify = "classify"
	StructPhasePolish   = "polish"
	StructPhaseFinalize = "finalize"
)

// maxPersistConcurrency bounds parallel DB writes in persist functions.
const maxPersistConcurrency = 5

const (
	maxDefraStructureWriteAttempts = 4
	defraStructureWriteRetryDelay  = 75 * time.Millisecond
)

// StartStructurePhase initializes and starts the structure phase.
func (j *Job) StartStructurePhase(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Mark structure as started
	if err := j.Book.StructureStart(); err != nil {
		if logger != nil {
			logger.Debug("structure already started", "error", err)
		}
		return nil
	}
	// Use async persist: memory is already updated by StructureStart(),
	// fire-and-forget DB write removes latency from critical path
	j.Book.PersistOpStateAsync(ctx, common.OpStructure)

	// Load linked entries (uses cache, refreshed after finalize_toc)
	entries, err := common.RefreshLinkedEntries(ctx, j.Book, j.TocDocID)
	if err != nil {
		j.noWorkFailure = fmt.Sprintf("structure failed to load linked ToC entries: %v", err)
		if logger != nil {
			logger.Error("failed to load linked entries for structure",
				"book_id", j.Book.BookID,
				"error", err)
		}
		j.Book.StructureFail(MaxBookOpRetries)
		j.Book.PersistOpStateAsync(ctx, common.OpStructure)
		return nil
	}

	// Initialize structure state on BookState
	j.Book.SetStructureChapters(make([]*common.ChapterState, 0))
	j.Book.SetStructureClassifications(make(map[string]string))
	j.Book.SetStructureClassifyReasonings(make(map[string]string))

	if logger != nil {
		logger.Info("starting structure phase",
			"book_id", j.Book.BookID,
			"linked_entries", len(entries))
	}

	// Phase 1: Build skeleton (synchronous)
	j.Book.SetStructurePhase(StructPhaseBuild)
	if err := j.buildChapterSkeleton(ctx, entries); err != nil {
		j.noWorkFailure = fmt.Sprintf("structure failed to build chapter skeleton: %v", err)
		if logger != nil {
			logger.Error("failed to build skeleton", "error", err)
		}
		j.Book.StructureFail(MaxBookOpRetries)
		j.Book.PersistOpStateAsync(ctx, common.OpStructure)
		return nil
	}
	j.noWorkFailure = ""

	// Update progress (async - memory is updated by SetStructureProgress)
	chapters := j.Book.GetStructureChapters()
	j.Book.SetStructureProgress(len(chapters), 0, 0, 0)
	j.Book.PersistStructurePhaseAsync(ctx)

	// Phase 2: Extract text (synchronous)
	j.Book.SetStructurePhase(StructPhaseExtract)
	chaptersExtracted := j.extractAllChapters(ctx)

	// Update progress (async - memory is authoritative during execution)
	j.Book.SetStructureProgress(len(chapters), chaptersExtracted, 0, 0)
	common.PersistStructurePhaseAsync(ctx, j.Book)

	// Persist extract results
	if err := j.persistExtractResults(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to persist extract results", "error", err)
		}
	}

	// Phase 3: Classify (LLM work unit)
	return j.transitionToStructureClassify(ctx)
}

func gqlString(s string) string {
	b, err := json.Marshal(s)
	if err != nil {
		return `""`
	}
	return string(b)
}

func isDefraDocIDExistsError(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "document with the given id already exists") ||
		strings.Contains(msg, "document with given id already exists")
}

func isDefraTransactionConflictError(err error) bool {
	if err == nil {
		return false
	}
	return strings.Contains(strings.ToLower(err.Error()), "transaction conflict")
}

func defraStructureWriteWithRetry(ctx context.Context, write func() (defra.WriteResult, error)) (defra.WriteResult, error) {
	var result defra.WriteResult
	var err error
	for attempt := 0; attempt < maxDefraStructureWriteAttempts; attempt++ {
		result, err = write()
		if err == nil || !isDefraTransactionConflictError(err) {
			return result, err
		}
		if attempt == maxDefraStructureWriteAttempts-1 {
			return result, err
		}
		delay := defraStructureWriteRetryDelay * time.Duration(attempt+1)
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return defra.WriteResult{}, ctx.Err()
		case <-timer.C:
		}
	}
	return result, err
}
