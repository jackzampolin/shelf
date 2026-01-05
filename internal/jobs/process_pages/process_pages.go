package process_pages

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	pjob "github.com/jackzampolin/shelf/internal/jobs/process_pages/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "process-pages"

// Config configures the process pages job.
type Config struct {
	OcrProviders     []string
	BlendProvider    string
	LabelProvider    string
	MetadataProvider string
	TocProvider      string
	DebugAgents      bool // Enable debug logging for agent executions
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if len(c.OcrProviders) == 0 {
		return fmt.Errorf("at least one OCR provider is required")
	}
	if c.BlendProvider == "" {
		return fmt.Errorf("blend provider is required")
	}
	if c.LabelProvider == "" {
		return fmt.Errorf("label provider is required")
	}
	if c.MetadataProvider == "" {
		return fmt.Errorf("metadata provider is required")
	}
	if c.TocProvider == "" {
		return fmt.Errorf("toc provider is required")
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
	})
	if err != nil {
		return nil, fmt.Errorf("failed to load book: %w", err)
	}

	logger := svcctx.LoggerFrom(ctx)
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
	return func(ctx context.Context, id string, metadata map[string]any) (jobs.Job, error) {
		bookID, ok := metadata["book_id"].(string)
		if !ok {
			return nil, fmt.Errorf("missing book_id in job metadata")
		}

		job, err := NewJob(ctx, cfg, bookID)
		if err != nil {
			return nil, err
		}

		// Set the persisted record ID
		job.SetRecordID(id)
		return job, nil
	}
}

