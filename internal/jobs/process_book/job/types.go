package job

import (
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
	common.BaseJob
	Tracker *common.WorkUnitTracker[WorkUnitInfo]

	// ToC agent (stateful during execution)
	TocAgent *agent.Agent
	TocDocID string
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
// This is the primary constructor - LoadBook does all the loading.
func NewFromLoadResult(result *common.LoadBookResult) *Job {
	return &Job{
		BaseJob: common.BaseJob{
			Book: result.Book,
		},
		Tracker:  common.NewWorkUnitTracker[WorkUnitInfo](),
		TocDocID: result.TocDocID,
	}
}

// Type returns the job type identifier.
func (j *Job) Type() string {
	return "process-book"
}

// MetricsFor returns base metrics attribution for this job.
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return j.BaseJob.MetricsFor(j.Type())
}

// RegisterWorkUnit registers a pending work unit.
func (j *Job) RegisterWorkUnit(unitID string, info WorkUnitInfo) {
	j.Tracker.Register(unitID, info)
}

// GetWorkUnit gets a pending work unit without removing it.
func (j *Job) GetWorkUnit(unitID string) (WorkUnitInfo, bool) {
	return j.Tracker.Get(unitID)
}

// RemoveWorkUnit removes a pending work unit.
func (j *Job) RemoveWorkUnit(unitID string) {
	j.Tracker.Remove(unitID)
}

// GetAndRemoveWorkUnit gets and removes a pending work unit.
func (j *Job) GetAndRemoveWorkUnit(unitID string) (WorkUnitInfo, bool) {
	return j.Tracker.GetAndRemove(unitID)
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

// FindPDFForPage returns the PDF path and page number within that PDF for a given output page number.
// Returns empty string and 0 if page is out of range.
func (j *Job) FindPDFForPage(pageNum int) (pdfPath string, pageInPDF int) {
	return j.Book.PDFs.FindPDFForPage(pageNum)
}
