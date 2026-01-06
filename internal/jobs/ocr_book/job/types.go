package job

import (
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// MaxPageOpRetries is the maximum number of retries for page-level operations.
const MaxPageOpRetries = 3

// BookStatus represents the top-level status of a book.
type BookStatus string

const (
	BookStatusIngested   BookStatus = "ingested"
	BookStatusProcessing BookStatus = "processing"
	BookStatusComplete   BookStatus = "complete"
)

// WorkUnitType constants for type-safe work unit handling.
const (
	WorkUnitTypeExtract = "extract"
	WorkUnitTypeOCR     = "ocr"
	WorkUnitTypeBlend   = "blend"
)

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	PageNum    int
	UnitType   string // Use WorkUnitType* constants
	Provider   string // for OCR units
	RetryCount int
}

// PageState is an alias for common.PageState.
type PageState = common.PageState

// Job processes all pages through Extract -> OCR -> Blend.
// This is a simpler job than process_book - no label, metadata, or ToC.
type Job struct {
	common.TrackedBaseJob[WorkUnitInfo]
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
func NewFromLoadResult(result *common.LoadBookResult) *Job {
	return &Job{
		TrackedBaseJob: common.NewTrackedBaseJob[WorkUnitInfo](result.Book),
	}
}

// Type returns the job type identifier.
func (j *Job) Type() string {
	return "ocr-book"
}

// MetricsFor returns base metrics attribution for this job.
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return j.BaseJob.MetricsFor(j.Type())
}

// FindPDFForPage returns the PDF path and page number within that PDF.
func (j *Job) FindPDFForPage(pageNum int) (pdfPath string, pageInPDF int) {
	return j.Book.PDFs.FindPDFForPage(pageNum)
}

// AllPagesBlendComplete returns true if all pages have completed blend.
func (j *Job) AllPagesBlendComplete() bool {
	allDone := true
	j.Book.ForEachPage(func(pageNum int, state *PageState) {
		if !state.IsBlendDone() {
			allDone = false
		}
	})
	return allDone && j.Book.CountPages() >= j.Book.TotalPages
}
