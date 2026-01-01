package ocr

import (
	"sync"

	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// JobType is the type identifier for OCR jobs.
const JobType = "ocr"

// Config for creating a new OCR job.
type Config struct {
	BookID       string
	TotalPages   int
	HomeDir      *home.Dir
	PDFs         common.PDFList // PDF sources for extraction
	OcrProviders []string
}

// WorkUnitInfo tracks pending work units for the OCR job.
type WorkUnitInfo struct {
	PageNum    int
	Provider   string // Empty for extract work units
	UnitType   string // "extract" or "ocr"
	RetryCount int
}

// Job processes all pages through OCR using multiple providers.
type Job struct {
	mu sync.Mutex

	// Configuration
	BookID       string
	TotalPages   int
	HomeDir      *home.Dir
	PDFs         common.PDFList // PDF sources for extraction
	OcrProviders []string

	// Job state
	RecordID string
	IsDone   bool

	// Page tracking
	PageState map[int]*PageState // page_num -> state

	// Work unit tracking
	PendingUnits map[string]WorkUnitInfo // work_unit_id -> info

	// Counts for progress
	TotalExpected  int // Total work units expected (pages × providers)
	TotalCompleted int // Work units completed
}

// New creates a new OCR job.
func New(cfg Config) *Job {
	return &Job{
		BookID:       cfg.BookID,
		TotalPages:   cfg.TotalPages,
		HomeDir:      cfg.HomeDir,
		PDFs:         cfg.PDFs,
		OcrProviders: cfg.OcrProviders,
		PageState:    make(map[int]*PageState),
		PendingUnits: make(map[string]WorkUnitInfo),
	}
}
