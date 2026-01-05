package job

import (
	"sync"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// LabelThresholdForBookOps is the number of labeled pages before triggering book-level operations.
const LabelThresholdForBookOps = 20

// BookStatus represents the top-level status of a book.
type BookStatus string

const (
	BookStatusIngested   BookStatus = "ingested"
	BookStatusProcessing BookStatus = "processing"
	BookStatusComplete   BookStatus = "complete"
)

// FrontMatterPageCount is the number of pages considered front matter for ToC search.
const FrontMatterPageCount = 50

// ConsecutiveFrontMatterRequired is the number of consecutive pages from page 1
// that must have blend_complete before starting ToC finder. This ensures the ToC
// pages (typically in first 20-30 pages) have blend output before the agent runs.
// Set to 50 to ensure adequate coverage for books with longer front matter.
const ConsecutiveFrontMatterRequired = 50

// PageState is an alias for common.PageState.
type PageState = common.PageState

// NewPageState creates a new page state with initialized maps.
func NewPageState() *PageState {
	return common.NewPageState()
}

// OpStatus is an alias for common.OpStatus.
type OpStatus = common.OpStatus

// Operation status constants - re-export from common.
const (
	OpNotStarted = common.OpNotStarted
	OpInProgress = common.OpInProgress
	OpComplete   = common.OpComplete
	OpFailed     = common.OpFailed
)

// OperationState is an alias for common.OperationState.
type OperationState = common.OperationState

// MaxBookOpRetries is the maximum number of retries for book-level operations.
const MaxBookOpRetries = 3

// MaxPageOpRetries is the maximum number of retries for page-level operations.
const MaxPageOpRetries = 3

// WorkUnitType constants for type-safe work unit handling.
const (
	WorkUnitTypeExtract    = "extract"
	WorkUnitTypeOCR        = "ocr"
	WorkUnitTypeBlend      = "blend"
	WorkUnitTypeLabel      = "label"
	WorkUnitTypeMetadata   = "metadata"
	WorkUnitTypeTocFinder  = "toc_finder"
	WorkUnitTypeTocExtract = "toc_extract"
)

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	PageNum    int
	UnitType   string // Use WorkUnitType* constants
	Provider   string // for OCR units
	RetryCount int    // number of times this work unit has been retried
}

// PDFInfo is an alias for common.PDFInfo for backwards compatibility.
type PDFInfo = common.PDFInfo

// Job processes all pages through Extract -> OCR -> Blend -> Label,
// then triggers book-level operations (metadata, ToC).
// Services (DefraClient, DefraSink) are accessed via svcctx from the context
// passed to Start() and OnComplete().
type Job struct {
	mu sync.Mutex

	// Book state (config, pages, prompts, operation state)
	Book *common.BookState

	// Job-specific state
	RecordID string
	IsDone   bool

	// ToC agent (stateful during execution)
	TocAgent *agent.Agent
	TocDocID string

	// Work unit tracking
	PendingUnits map[string]WorkUnitInfo // work_unit_id -> info
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
// This is the primary constructor - LoadBook does all the loading.
func NewFromLoadResult(result *common.LoadBookResult) *Job {
	return &Job{
		Book:         result.Book,
		TocDocID:     result.TocDocID,
		PendingUnits: make(map[string]WorkUnitInfo),
	}
}

// CountLabeledPages returns the number of pages that have completed labeling.
func (j *Job) CountLabeledPages() int {
	return j.Book.CountLabeledPages()
}

// ConsecutiveFrontMatterComplete returns true if pages 1 through ConsecutiveFrontMatterRequired
// all have blend_complete. This ensures the ToC finder has OCR data for the pages where
// the ToC is typically located.
func (j *Job) ConsecutiveFrontMatterComplete() bool {
	return j.Book.ConsecutivePagesComplete(ConsecutiveFrontMatterRequired)
}

// AllPagesComplete returns true if all pages have completed the page-level pipeline.
func (j *Job) AllPagesComplete() bool {
	return j.Book.AllPagesComplete()
}

// RegisterWorkUnit registers a pending work unit.
func (j *Job) RegisterWorkUnit(unitID string, info WorkUnitInfo) {
	j.PendingUnits[unitID] = info
}

// GetWorkUnit gets a pending work unit without removing it.
func (j *Job) GetWorkUnit(unitID string) (WorkUnitInfo, bool) {
	info, ok := j.PendingUnits[unitID]
	return info, ok
}

// RemoveWorkUnit removes a pending work unit.
func (j *Job) RemoveWorkUnit(unitID string) {
	delete(j.PendingUnits, unitID)
}

// GetAndRemoveWorkUnit gets and removes a pending work unit.
func (j *Job) GetAndRemoveWorkUnit(unitID string) (WorkUnitInfo, bool) {
	info, ok := j.PendingUnits[unitID]
	if ok {
		delete(j.PendingUnits, unitID)
	}
	return info, ok
}

// MetricsFor returns base metrics attribution for this job.
// Returns BookID and Stage pre-filled. Callers add ItemKey for specific work units.
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return &jobs.WorkUnitMetrics{
		BookID: j.Book.BookID,
		Stage:  j.Type(),
	}
}

// FindPDFForPage returns the PDF path and page number within that PDF for a given output page number.
// Returns empty string and 0 if page is out of range.
func (j *Job) FindPDFForPage(pageNum int) (pdfPath string, pageInPDF int) {
	return j.Book.PDFs.FindPDFForPage(pageNum)
}

// ProviderProgress returns progress by provider for the Progress() method.
func (j *Job) ProviderProgress() map[string]jobs.ProviderProgress {
	// Get progress from BookState and convert to jobs.ProviderProgress
	bookProgress := j.Book.GetProviderProgress()
	progress := make(map[string]jobs.ProviderProgress, len(bookProgress))
	for key, p := range bookProgress {
		progress[key] = jobs.ProviderProgress{
			TotalExpected: p.TotalExpected,
			Completed:     p.Completed,
		}
	}
	return progress
}
