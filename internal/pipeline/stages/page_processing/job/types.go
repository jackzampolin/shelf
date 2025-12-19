package job

import (
	"sync"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs"
)

// LabelThresholdForBookOps is the number of labeled pages before triggering book-level operations.
const LabelThresholdForBookOps = 20

// PageState tracks the processing state of a single page.
type PageState struct {
	PageDocID string // DefraDB document ID for the Page record

	// Extraction state (from PDF)
	ExtractDone bool

	// OCR state per provider
	OcrResults map[string]string // provider -> OCR text
	OcrDone    map[string]bool   // provider -> completed

	// Pipeline state
	BlendDone   bool
	BlendedText string // Cached blend result for label work unit
	LabelDone   bool
}

// NewPageState creates a new page state.
func NewPageState() *PageState {
	return &PageState{
		OcrResults: make(map[string]string),
		OcrDone:    make(map[string]bool),
	}
}

// MaxBookOpRetries is the maximum number of retries for book-level operations.
const MaxBookOpRetries = 3

// BookState tracks book-level processing state.
type BookState struct {
	MetadataStarted  bool
	MetadataComplete bool
	MetadataFailed   bool // Permanently failed after max retries
	MetadataRetries  int

	// ToC finder state
	TocFinderStarted bool
	TocFinderDone    bool
	TocFinderFailed  bool // Permanently failed after max retries
	TocFinderRetries int
	TocFound         bool
	TocStartPage     int
	TocEndPage       int

	// ToC extract state
	TocExtractStarted bool
	TocExtractDone    bool
	TocExtractFailed  bool // Permanently failed after max retries
	TocExtractRetries int
}

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	PageNum  int
	UnitType string // "extract", "ocr", "blend", "label", "metadata", "toc_finder", "toc_extract"
	Provider string // for OCR units
}

// PDFInfo describes a PDF file and its page range.
type PDFInfo struct {
	Path      string // Full path to the PDF
	StartPage int    // First page number (1-indexed, cumulative)
	EndPage   int    // Last page number (inclusive)
}

// Job processes all pages through Extract -> OCR -> Blend -> Label,
// then triggers book-level operations (metadata, ToC).
// Services (DefraClient, DefraSink) are accessed via svcctx from the context
// passed to Start() and OnComplete().
type Job struct {
	Mu sync.Mutex

	// Configuration
	BookID           string
	TotalPages       int
	HomeDir          *home.Dir
	OcrProviders     []string
	BlendProvider    string
	LabelProvider    string
	MetadataProvider string
	TocProvider      string

	// PDF sources for extraction
	PDFs []PDFInfo // Sorted by StartPage

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
		PageState:        make(map[int]*PageState),
		PendingUnits:     make(map[string]WorkUnitInfo),
	}
}

// Config for creating a new Job.
type Config struct {
	BookID           string
	TotalPages       int
	HomeDir          *home.Dir
	PDFs             []PDFInfo // PDF sources for extraction
	OcrProviders     []string
	BlendProvider    string
	LabelProvider    string
	MetadataProvider string
	TocProvider      string
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
	for _, pdf := range j.PDFs {
		if pageNum >= pdf.StartPage && pageNum <= pdf.EndPage {
			// pageInPDF is 1-indexed within this PDF
			pageInPDF = pageNum - pdf.StartPage + 1
			return pdf.Path, pageInPDF
		}
	}
	return "", 0
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
