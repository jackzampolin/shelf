package ocr

import (
	"fmt"
	"sync"

	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// JobType is the type identifier for OCR jobs.
const JobType = "ocr"

// WorkUnitType constants for type-safe work unit handling.
const (
	WorkUnitTypeExtract = "extract"
	WorkUnitTypeOCR     = "ocr"
)

// Config for creating a new OCR job.
type Config struct {
	BookID       string
	TotalPages   int
	HomeDir      *home.Dir
	PDFs         common.PDFList // PDF sources for extraction
	OcrProviders []string
}

// Validate checks that the Config has all required fields set.
func (c Config) Validate() error {
	if c.BookID == "" {
		return fmt.Errorf("BookID is required")
	}
	if c.TotalPages <= 0 {
		return fmt.Errorf("TotalPages must be positive")
	}
	if c.HomeDir == nil {
		return fmt.Errorf("HomeDir is required")
	}
	if len(c.OcrProviders) == 0 {
		return fmt.Errorf("at least one OcrProvider is required")
	}
	return nil
}

// WorkUnitInfo tracks pending work units for the OCR job.
type WorkUnitInfo struct {
	PageNum    int
	Provider   string // Empty for extract work units
	UnitType   string // Use WorkUnitTypeExtract or WorkUnitTypeOCR constants
	RetryCount int
}

// Job processes all pages through OCR using multiple providers.
type Job struct {
	mu sync.Mutex

	// Configuration (immutable after construction)
	BookID       string
	TotalPages   int
	HomeDir      *home.Dir
	PDFs         common.PDFList // PDF sources for extraction
	OcrProviders []string

	// Job state (mutable, protected by mu)
	RecordID       string
	isDone         bool
	pageState      map[int]*PageState    // page_num -> state
	pendingUnits   map[string]WorkUnitInfo // work_unit_id -> info
	totalExpected  int // Total work units expected (pages × providers)
	totalCompleted int // Work units completed
}

// New creates a new OCR job.
func New(cfg Config) *Job {
	return &Job{
		BookID:       cfg.BookID,
		TotalPages:   cfg.TotalPages,
		HomeDir:      cfg.HomeDir,
		PDFs:         cfg.PDFs,
		OcrProviders: cfg.OcrProviders,
		pageState:    make(map[int]*PageState),
		pendingUnits: make(map[string]WorkUnitInfo),
	}
}
