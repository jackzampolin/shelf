package job

import (
	"fmt"
	"sync"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/jobs/ocr"
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

// PageState tracks the processing state of a single page.
// Embeds ocr.PageState for OCR-related fields.
type PageState struct {
	*ocr.PageState // Embedded: PageDocID, ExtractDone, OcrResults, OcrDone

	// Pipeline state (beyond OCR)
	BlendDone   bool
	BlendedText string // Cached blend result for label work unit
	LabelDone   bool
}

// NewPageState creates a new page state.
func NewPageState() *PageState {
	return &PageState{
		PageState: ocr.NewPageState(),
	}
}

// MaxBookOpRetries is the maximum number of retries for book-level operations.
const MaxBookOpRetries = 3

// OpStatus represents the status of a book-level operation.
type OpStatus int

const (
	OpNotStarted OpStatus = iota
	OpInProgress
	OpComplete
	OpFailed
)

// String returns the string representation of the status.
func (s OpStatus) String() string {
	switch s {
	case OpNotStarted:
		return "not_started"
	case OpInProgress:
		return "in_progress"
	case OpComplete:
		return "complete"
	case OpFailed:
		return "failed"
	default:
		return "unknown"
	}
}

// OperationState tracks the state of a retriable book-level operation.
type OperationState struct {
	Status  OpStatus
	Retries int
}

// Start marks the operation as in progress. Returns error if already started.
func (o *OperationState) Start() error {
	if o.Status != OpNotStarted {
		return fmt.Errorf("operation already %s", o.Status)
	}
	o.Status = OpInProgress
	return nil
}

// Complete marks the operation as successfully completed.
func (o *OperationState) Complete() {
	o.Status = OpComplete
}

// Fail records a failure and returns true if permanently failed (max retries reached).
func (o *OperationState) Fail(maxRetries int) bool {
	o.Retries++
	if o.Retries >= maxRetries {
		o.Status = OpFailed
		return true
	}
	o.Status = OpNotStarted // Allow retry
	return false
}

// IsStarted returns true if the operation has been started.
func (o *OperationState) IsStarted() bool {
	return o.Status == OpInProgress
}

// IsDone returns true if the operation is complete or permanently failed.
func (o *OperationState) IsDone() bool {
	return o.Status == OpComplete || o.Status == OpFailed
}

// IsFailed returns true if the operation permanently failed.
func (o *OperationState) IsFailed() bool {
	return o.Status == OpFailed
}

// IsComplete returns true if the operation completed successfully.
func (o *OperationState) IsComplete() bool {
	return o.Status == OpComplete
}

// CanStart returns true if the operation can be started (not started, not done).
func (o *OperationState) CanStart() bool {
	return o.Status == OpNotStarted
}

// BookState tracks book-level processing state.
type BookState struct {
	Metadata   OperationState
	TocFinder  OperationState
	TocExtract OperationState

	// ToC finder results (set when TocFinder completes successfully)
	TocFound     bool
	TocStartPage int
	TocEndPage   int
}

// MaxPageOpRetries is the maximum number of retries for page-level operations.
const MaxPageOpRetries = 3

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	PageNum    int
	UnitType   string // "extract", "ocr", "blend", "label", "metadata", "toc_finder", "toc_extract"
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

	// Configuration
	BookID           string
	TotalPages       int
	HomeDir          *home.Dir
	OcrProviders     []string
	BlendProvider    string
	LabelProvider    string
	MetadataProvider string
	TocProvider      string
	DebugAgents      bool // Enable debug logging for agent executions

	// PDF sources for extraction
	PDFs common.PDFList // Sorted by StartPage

	// Job state
	RecordID string
	IsDone   bool

	// Page tracking
	PageState map[int]*PageState // page_num -> state

	// Book-level tracking
	BookState BookState

	// ToC agent (stateful during execution)
	TocAgent *agent.Agent
	TocDocID string

	// Work unit tracking
	PendingUnits map[string]WorkUnitInfo // work_unit_id -> info

	// Resolved prompts (cached at job start for book-level overrides)
	ResolvedPrompts map[string]string // prompt_key -> resolved text
	ResolvedCIDs    map[string]string // prompt_key -> CID for traceability
}

// New creates a new Job with initialized maps.
func New(cfg Config) *Job {
	return &Job{
		BookID:           cfg.BookID,
		TotalPages:       cfg.TotalPages,
		HomeDir:          cfg.HomeDir,
		PDFs:             cfg.PDFs,
		OcrProviders:     cfg.OcrProviders,
		BlendProvider:    cfg.BlendProvider,
		LabelProvider:    cfg.LabelProvider,
		MetadataProvider: cfg.MetadataProvider,
		TocProvider:      cfg.TocProvider,
		DebugAgents:      cfg.DebugAgents,
		PageState:        make(map[int]*PageState),
		PendingUnits:     make(map[string]WorkUnitInfo),
		ResolvedPrompts:  make(map[string]string),
		ResolvedCIDs:     make(map[string]string),
	}
}

// Config for creating a new Job.
type Config struct {
	BookID           string
	TotalPages       int
	HomeDir          *home.Dir
	PDFs             common.PDFList // PDF sources for extraction
	OcrProviders     []string
	BlendProvider    string
	LabelProvider    string
	MetadataProvider string
	TocProvider      string
	DebugAgents      bool // Enable debug logging for agent executions
}

// CountLabeledPages returns the number of pages that have completed labeling.
func (j *Job) CountLabeledPages() int {
	count := 0
	for _, state := range j.PageState {
		if state.LabelDone {
			count++
		}
	}
	return count
}

// ConsecutiveFrontMatterComplete returns true if pages 1 through ConsecutiveFrontMatterRequired
// all have blend_complete. This ensures the ToC finder has OCR data for the pages where
// the ToC is typically located.
func (j *Job) ConsecutiveFrontMatterComplete() bool {
	required := ConsecutiveFrontMatterRequired
	if j.TotalPages < required {
		required = j.TotalPages
	}
	for pageNum := 1; pageNum <= required; pageNum++ {
		state, ok := j.PageState[pageNum]
		if !ok || !state.BlendDone {
			return false
		}
	}
	return true
}

// AllPagesComplete returns true if all pages have completed the page-level pipeline.
func (j *Job) AllPagesComplete() bool {
	for _, state := range j.PageState {
		if !state.LabelDone {
			return false
		}
	}
	return len(j.PageState) >= j.TotalPages
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
		BookID: j.BookID,
		Stage:  j.Type(),
	}
}

// FindPDFForPage returns the PDF path and page number within that PDF for a given output page number.
// Returns empty string and 0 if page is out of range.
func (j *Job) FindPDFForPage(pageNum int) (pdfPath string, pageInPDF int) {
	return j.PDFs.FindPDFForPage(pageNum)
}

// ProviderProgress returns progress by provider for the Progress() method.
func (j *Job) ProviderProgress() map[string]jobs.ProviderProgress {
	progress := make(map[string]jobs.ProviderProgress)

	// Track extraction progress
	extractCompleted := 0
	for _, state := range j.PageState {
		if state.ExtractDone {
			extractCompleted++
		}
	}
	progress["extract"] = jobs.ProviderProgress{
		TotalExpected: j.TotalPages,
		Completed:     extractCompleted,
	}

	// Track OCR progress per provider
	for _, provider := range j.OcrProviders {
		completed := 0
		for _, state := range j.PageState {
			if state.OcrDone[provider] {
				completed++
			}
		}
		progress[provider] = jobs.ProviderProgress{
			TotalExpected: j.TotalPages,
			Completed:     completed,
		}
	}

	// Track blend progress
	blendCompleted := 0
	for _, state := range j.PageState {
		if state.BlendDone {
			blendCompleted++
		}
	}
	progress["blend"] = jobs.ProviderProgress{
		TotalExpected: j.TotalPages,
		Completed:     blendCompleted,
	}

	// Track label progress
	labelCompleted := 0
	for _, state := range j.PageState {
		if state.LabelDone {
			labelCompleted++
		}
	}
	progress["label"] = jobs.ProviderProgress{
		TotalExpected: j.TotalPages,
		Completed:     labelCompleted,
	}

	return progress
}
