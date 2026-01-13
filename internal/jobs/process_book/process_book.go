package process_book

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	pjob "github.com/jackzampolin/shelf/internal/jobs/process_book/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "process-book"

// Config configures the process pages job.
type Config struct {
	// Provider settings
	OcrProviders     []string
	BlendProvider    string
	LabelProvider    string
	MetadataProvider string
	TocProvider      string
	DebugAgents      bool   // Enable debug logging for agent executions
	ResetFrom        string // If set, reset this operation and all downstream dependencies before starting

	// Pipeline stage toggles (all default to true for standard processing)
	// When disabled, the stage is skipped entirely.
	EnableOCR             bool // Run OCR on pages (required for text-based stages)
	EnableBlend           bool // Run blend to merge OCR outputs
	EnableLabel           bool // Run page labeling
	EnableMetadata        bool // Extract book metadata
	EnableTocFinder       bool // Find ToC pages
	EnableTocExtract      bool // Extract ToC entries
	EnablePatternAnalysis bool // Analyze page patterns
	EnableTocLink         bool // Link ToC entries to pages
	EnableTocFinalize     bool // Run finalize phase (pattern/discover/gap)
	EnableStructure       bool // Build chapter structure
}

// PipelineVariant represents a predefined pipeline configuration.
type PipelineVariant string

const (
	// VariantStandard is the full pipeline for standard books with ToC.
	VariantStandard PipelineVariant = "standard"
	// VariantPhotoBook is a minimal pipeline for photo books (no ToC, minimal text).
	VariantPhotoBook PipelineVariant = "photo-book"
	// VariantTextOnly processes text only (OCR + blend, no ToC or labels).
	VariantTextOnly PipelineVariant = "text-only"
	// VariantOCROnly runs only OCR without any LLM processing.
	VariantOCROnly PipelineVariant = "ocr-only"
)

// ApplyVariant applies predefined settings for a pipeline variant.
// This sets the Enable* flags appropriately for the variant.
func (c *Config) ApplyVariant(variant PipelineVariant) {
	switch variant {
	case VariantPhotoBook:
		// Photo books: OCR + blend only, no ToC or structure
		c.EnableOCR = true
		c.EnableBlend = true
		c.EnableLabel = true
		c.EnableMetadata = true
		c.EnableTocFinder = false
		c.EnableTocExtract = false
		c.EnablePatternAnalysis = false
		c.EnableTocLink = false
		c.EnableTocFinalize = false
		c.EnableStructure = false

	case VariantTextOnly:
		// Text extraction only: OCR + blend
		c.EnableOCR = true
		c.EnableBlend = true
		c.EnableLabel = false
		c.EnableMetadata = true
		c.EnableTocFinder = false
		c.EnableTocExtract = false
		c.EnablePatternAnalysis = false
		c.EnableTocLink = false
		c.EnableTocFinalize = false
		c.EnableStructure = false

	case VariantOCROnly:
		// OCR only: no LLM processing at all
		c.EnableOCR = true
		c.EnableBlend = false
		c.EnableLabel = false
		c.EnableMetadata = false
		c.EnableTocFinder = false
		c.EnableTocExtract = false
		c.EnablePatternAnalysis = false
		c.EnableTocLink = false
		c.EnableTocFinalize = false
		c.EnableStructure = false

	default: // VariantStandard
		// Standard: full pipeline
		c.EnableOCR = true
		c.EnableBlend = true
		c.EnableLabel = true
		c.EnableMetadata = true
		c.EnableTocFinder = true
		c.EnableTocExtract = true
		c.EnablePatternAnalysis = true
		c.EnableTocLink = true
		c.EnableTocFinalize = true
		c.EnableStructure = true
	}
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	// OCR providers required if OCR is enabled
	if c.EnableOCR && len(c.OcrProviders) == 0 {
		return fmt.Errorf("at least one OCR provider is required when OCR is enabled")
	}
	// Blend provider required if blend is enabled
	if c.EnableBlend && c.BlendProvider == "" {
		return fmt.Errorf("blend provider is required when blend is enabled")
	}
	// Label provider required if label is enabled
	if c.EnableLabel && c.LabelProvider == "" {
		return fmt.Errorf("label provider is required when label is enabled")
	}
	// Metadata provider required if metadata is enabled
	if c.EnableMetadata && c.MetadataProvider == "" {
		return fmt.Errorf("metadata provider is required when metadata is enabled")
	}
	// ToC provider required if any ToC stage is enabled
	tocEnabled := c.EnableTocFinder || c.EnableTocExtract || c.EnableTocLink || c.EnableTocFinalize || c.EnableStructure
	if tocEnabled && c.TocProvider == "" {
		return fmt.Errorf("toc provider is required when ToC stages are enabled")
	}
	if c.ResetFrom != "" && !common.IsValidResetOperation(c.ResetFrom) {
		return fmt.Errorf("invalid reset operation: %s (valid: %v)", c.ResetFrom, common.ValidResetOperations)
	}
	return nil
}

// Status represents the status of page processing for a book.
type Status struct {
	TotalPages       int  `json:"total_pages"`
	OcrComplete      int  `json:"ocr_complete"`
	BlendComplete    int  `json:"blend_complete"`
	LabelComplete    int  `json:"label_complete"`
	MetadataComplete bool `json:"metadata_complete"`
	TocFound         bool `json:"toc_found"`
	TocExtracted     bool `json:"toc_extracted"`
}

// IsComplete returns whether processing is complete for this book.
func (st *Status) IsComplete() bool {
	allPagesComplete := st.LabelComplete >= st.TotalPages
	return allPagesComplete && st.MetadataComplete && st.TocExtracted
}

// GetStatus queries DefraDB for the current processing status of a book.
func GetStatus(ctx context.Context, bookID string) (*Status, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	return GetStatusWithClient(ctx, defraClient, bookID)
}

// GetStatusWithClient queries DefraDB for status using the provided client.
func GetStatusWithClient(ctx context.Context, client *defra.Client, bookID string) (*Status, error) {
	// Query book for total pages and metadata status
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			page_count
			metadata_complete
		}
	}`, bookID)

	bookResp, err := client.Execute(ctx, bookQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query book: %w", err)
	}

	status := &Status{}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if book, ok := books[0].(map[string]any); ok {
			if pc, ok := book["page_count"].(float64); ok {
				status.TotalPages = int(pc)
			}
			if mc, ok := book["metadata_complete"].(bool); ok {
				status.MetadataComplete = mc
			}
		}
	}

	// Query page completion counts
	pageQuery := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}) {
			ocr_complete
			blend_complete
			label_complete
		}
	}`, bookID)

	pageResp, err := client.Execute(ctx, pageQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query pages: %w", err)
	}

	if pages, ok := pageResp.Data["Page"].([]any); ok {
		for _, p := range pages {
			page, ok := p.(map[string]any)
			if !ok {
				continue
			}
			if ocrComplete, ok := page["ocr_complete"].(bool); ok && ocrComplete {
				status.OcrComplete++
			}
			if blendComplete, ok := page["blend_complete"].(bool); ok && blendComplete {
				status.BlendComplete++
			}
			if labelComplete, ok := page["label_complete"].(bool); ok && labelComplete {
				status.LabelComplete++
			}
		}
	}

	// Query ToC status
	tocQuery := fmt.Sprintf(`{
		ToC(filter: {book_id: {_eq: "%s"}}) {
			toc_found
			extract_complete
		}
	}`, bookID)

	tocResp, err := client.Execute(ctx, tocQuery, nil)
	if err == nil {
		if tocs, ok := tocResp.Data["ToC"].([]any); ok && len(tocs) > 0 {
			if toc, ok := tocs[0].(map[string]any); ok {
				if found, ok := toc["toc_found"].(bool); ok {
					status.TocFound = found
				}
				if extracted, ok := toc["extract_complete"].(bool); ok {
					status.TocExtracted = extracted
				}
			}
		}
	}

	return status, nil
}

// NewJob creates a new process pages job for the given book.
// Uses common.LoadBook to load everything in one call.
func NewJob(ctx context.Context, cfg Config, bookID string) (jobs.Job, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("invalid config: %w", err)
	}

	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		return nil, fmt.Errorf("home directory not in context")
	}

	// Load everything about this book in one call
	result, err := common.LoadBook(ctx, bookID, common.LoadBookConfig{
		HomeDir:          homeDir,
		OcrProviders:     cfg.OcrProviders,
		BlendProvider:    cfg.BlendProvider,
		LabelProvider:    cfg.LabelProvider,
		MetadataProvider: cfg.MetadataProvider,
		TocProvider:      cfg.TocProvider,
		DebugAgents:      cfg.DebugAgents,
		PromptKeys:       pjob.PromptKeys(),
		// Pipeline stage toggles
		EnableOCR:             cfg.EnableOCR,
		EnableBlend:           cfg.EnableBlend,
		EnableLabel:           cfg.EnableLabel,
		EnableMetadata:        cfg.EnableMetadata,
		EnableTocFinder:       cfg.EnableTocFinder,
		EnableTocExtract:      cfg.EnableTocExtract,
		EnablePatternAnalysis: cfg.EnablePatternAnalysis,
		EnableTocLink:         cfg.EnableTocLink,
		EnableTocFinalize:     cfg.EnableTocFinalize,
		EnableStructure:       cfg.EnableStructure,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to load book: %w", err)
	}

	logger := svcctx.LoggerFrom(ctx)

	// If reset requested, reset the operation and all downstream dependencies
	if cfg.ResetFrom != "" {
		if logger != nil {
			logger.Info("resetting operation with cascade",
				"book_id", bookID,
				"reset_from", cfg.ResetFrom)
		}
		if err := common.ResetFrom(ctx, result.Book, result.TocDocID, common.ResetOperation(cfg.ResetFrom)); err != nil {
			return nil, fmt.Errorf("failed to reset from %s: %w", cfg.ResetFrom, err)
		}
	}

	if logger != nil {
		logger.Info("creating page processing job",
			"book_id", bookID,
			"total_pages", result.Book.TotalPages,
			"ocr_providers", cfg.OcrProviders)
	}

	return pjob.NewFromLoadResult(result), nil
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
// Used by the scheduler to resume interrupted jobs after restart.
func JobFactory(cfg Config) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		return NewJob(ctx, cfg, bookID)
	})
}

