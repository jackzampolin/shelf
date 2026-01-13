package job

import (
	"github.com/jackzampolin/shelf/internal/agent"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// BlendThresholdForMetadata is the number of blended pages before triggering metadata extraction.
// Metadata only needs blended text (not labels), so it can start early while OCR is still running.
const BlendThresholdForMetadata = 20

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
const ConsecutiveFrontMatterRequired = 30

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
	WorkUnitTypeExtract         = "extract"
	WorkUnitTypeOCR             = "ocr"
	WorkUnitTypeBlend           = "blend"
	WorkUnitTypeLabel           = "label"
	WorkUnitTypeMetadata        = "metadata"
	WorkUnitTypeTocFinder       = "toc_finder"
	WorkUnitTypeTocExtract      = "toc_extract"
	WorkUnitTypePatternAnalysis = "pattern_analysis"
	WorkUnitTypeLinkToc         = "link_toc"

	// Finalize ToC work unit types
	WorkUnitTypeFinalizePattern  = "finalize_pattern"
	WorkUnitTypeFinalizeDiscover = "finalize_discover"
	WorkUnitTypeFinalizeGap      = "finalize_gap"

	// Common structure work unit types
	WorkUnitTypeStructureClassify = "structure_classify"
	WorkUnitTypeStructurePolish   = "structure_polish"
)

// Finalize ToC phase constants.
const (
	FinalizePhasePending  = ""
	FinalizePhasePattern  = "pattern"
	FinalizePhaseDiscover = "discover"
	FinalizePhaseValidate = "validate"
	FinalizePhaseDone     = "done"
)

// Common structure phase constants.
const (
	StructurePhasePending  = ""
	StructurePhaseBuild    = "build"
	StructurePhaseExtract  = "extract"
	StructurePhaseClassify = "classify"
	StructurePhasePolish   = "polish"
	StructurePhaseFinalize = "finalize"
	StructurePhaseDone     = "done"
)

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	PageNum    int
	UnitType   string // Use WorkUnitType* constants
	Provider   string // for OCR units
	RetryCount int    // number of times this work unit has been retried
	EntryDocID string // for link_toc units - which ToC entry this belongs to

	// Pattern analysis fields
	PatternAnalysisSubtype string // page_numbers, chapters, boundaries

	// Finalize ToC fields
	FinalizePhase string // pattern, discover, validate
	FinalizeKey   string // entry key or gap key

	// Structure fields
	StructurePhase string // classify, polish
	ChapterID      string // chapter entry ID for polish
}

// PDFInfo is an alias for common.PDFInfo for backwards compatibility.
type PDFInfo = common.PDFInfo

// Job processes all pages through Extract -> OCR -> Blend -> Label,
// then triggers book-level operations (metadata, ToC, finalize, structure).
// Services (DefraClient, DefraSink) are accessed via svcctx from the context
// passed to Start() and OnComplete().
//
// State consolidation: Most state is stored on BookState (via j.Book).
// Only agent instances are stored directly on Job due to circular import constraints.
type Job struct {
	common.TrackedBaseJob[WorkUnitInfo]

	// ToC agent (stateful during execution)
	TocAgent *agent.Agent
	TocDocID string

	// Link ToC entry agents (one per ToC entry)
	LinkTocEntries     []*toc_entry_finder.TocEntry
	LinkTocEntryAgents map[string]*agent.Agent // keyed by entry DocID
	LinkTocEntriesDone int                     // count of completed entries

	// Finalize ToC agent maps (can't be on BookState due to circular imports)
	// Data state (PatternResult, EntriesToFind, Gaps) is on BookState
	FinalizeDiscoverAgents map[string]*agent.Agent // entryKey -> active agent
	FinalizeGapAgents      map[string]*agent.Agent // gapKey -> active agent

	// Finalize page pattern context (local to finalize phase execution)
	// Uses types.DetectedChapter which can't be in common due to import constraints
	FinalizePagePatternCtx *PagePatternContext
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
// This is the primary constructor - LoadBook does all the loading.
func NewFromLoadResult(result *common.LoadBookResult) *Job {
	return &Job{
		TrackedBaseJob:         common.NewTrackedBaseJob[WorkUnitInfo](result.Book),
		TocDocID:               result.TocDocID,
		LinkTocEntryAgents:     make(map[string]*agent.Agent),
		FinalizeDiscoverAgents: make(map[string]*agent.Agent),
		FinalizeGapAgents:      make(map[string]*agent.Agent),
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

// CountLabeledPages returns the number of pages that have completed labeling.
func (j *Job) CountLabeledPages() int {
	return j.Book.CountLabeledPages()
}

// CountBlendedPages returns the number of pages that have completed blend.
func (j *Job) CountBlendedPages() int {
	return j.Book.CountBlendedPages()
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

// AllPagesBlendComplete returns true if all pages have completed blend.
func (j *Job) AllPagesBlendComplete() bool {
	return j.Book.AllPagesBlendComplete()
}

// FindPDFForPage returns the PDF path and page number within that PDF for a given output page number.
// Returns empty string and 0 if page is out of range.
func (j *Job) FindPDFForPage(pageNum int) (pdfPath string, pageInPDF int) {
	return j.Book.PDFs.FindPDFForPage(pageNum)
}
