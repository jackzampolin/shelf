package ocr

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/svcctx"
)

// PreconditionError represents a failed precondition check.
type PreconditionError struct {
	Condition string
	Details   string
}

func (e *PreconditionError) Error() string {
	if e.Details != "" {
		return fmt.Sprintf("precondition failed: %s - %s", e.Condition, e.Details)
	}
	return fmt.Sprintf("precondition failed: %s", e.Condition)
}

// CheckPreconditions verifies all requirements are met before starting the job.
// Returns nil if all preconditions pass, otherwise returns a PreconditionError.
func (j *Job) CheckPreconditions(ctx context.Context) error {
	// Check DefraDB client is available
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return &PreconditionError{
			Condition: "defra_client_available",
			Details:   "DefraDB client not in context",
		}
	}

	// Check book exists in DefraDB
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			_docID
			title
		}
	}`, j.BookID)

	resp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return &PreconditionError{
			Condition: "book_exists",
			Details:   fmt.Sprintf("failed to query book: %v", err),
		}
	}

	books, ok := resp.Data["Book"].([]any)
	if !ok || len(books) == 0 {
		return &PreconditionError{
			Condition: "book_exists",
			Details:   fmt.Sprintf("book %s not found in DefraDB", j.BookID),
		}
	}

	// Check PDFs exist for extraction (if needed)
	if len(j.PDFs) == 0 {
		return &PreconditionError{
			Condition: "pdfs_available",
			Details:   "no PDFs found in originals directory for extraction",
		}
	}

	// Check OCR providers are configured
	if len(j.OcrProviders) == 0 {
		return &PreconditionError{
			Condition: "ocr_providers_configured",
			Details:   "no OCR providers configured",
		}
	}

	return nil
}
