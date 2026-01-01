package ocr

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// NewJob creates a new OCR job for the given book.
// OCR providers are read from the database config (defaults.ocr_providers).
func NewJob(ctx context.Context, bookID string) (jobs.Job, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		return nil, fmt.Errorf("home directory not in context")
	}

	configStore := svcctx.ConfigStoreFrom(ctx)
	if configStore == nil {
		return nil, fmt.Errorf("config store not in context")
	}

	// Read OCR providers from config
	providersEntry, err := configStore.Get(ctx, "defaults.ocr_providers")
	if err != nil {
		return nil, fmt.Errorf("failed to get OCR providers config: %w", err)
	}
	if providersEntry == nil {
		return nil, fmt.Errorf("OCR providers not configured (defaults.ocr_providers)")
	}

	// Parse providers list
	var ocrProviders []string
	switch v := providersEntry.Value.(type) {
	case []string:
		ocrProviders = v
	case []any:
		for _, p := range v {
			if s, ok := p.(string); ok {
				ocrProviders = append(ocrProviders, s)
			}
		}
	default:
		return nil, fmt.Errorf("invalid OCR providers config type: %T", providersEntry.Value)
	}

	if len(ocrProviders) == 0 {
		return nil, fmt.Errorf("no OCR providers configured")
	}

	// Get book info
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			page_count
		}
	}`, bookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query book: %w", err)
	}

	var totalPages int
	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if book, ok := books[0].(map[string]any); ok {
			if pc, ok := book["page_count"].(float64); ok {
				totalPages = int(pc)
			}
		}
	}

	if totalPages == 0 {
		return nil, fmt.Errorf("book %s has no pages", bookID)
	}

	// Load PDFs from originals directory
	pdfs, err := common.LoadPDFsFromOriginals(homeDir, bookID)
	if err != nil {
		return nil, fmt.Errorf("failed to load PDFs: %w", err)
	}

	if len(pdfs) == 0 {
		return nil, fmt.Errorf("no PDFs found in originals directory for book %s", bookID)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("creating OCR job", "book_id", bookID, "total_pages", totalPages, "providers", ocrProviders, "pdfs", len(pdfs))
	}

	return New(Config{
		BookID:       bookID,
		TotalPages:   totalPages,
		HomeDir:      homeDir,
		PDFs:         pdfs,
		OcrProviders: ocrProviders,
	}), nil
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
func JobFactory() jobs.JobFactory {
	return func(ctx context.Context, id string, metadata map[string]any) (jobs.Job, error) {
		bookID, ok := metadata["book_id"].(string)
		if !ok {
			return nil, fmt.Errorf("missing book_id in job metadata")
		}

		job, err := NewJob(ctx, bookID)
		if err != nil {
			return nil, err
		}

		job.SetRecordID(id)
		return job, nil
	}
}
