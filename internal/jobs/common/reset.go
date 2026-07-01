package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ResetOperation identifies an operation that can be reset.
type ResetOperation string

const (
	ResetMetadata    ResetOperation = "metadata"
	ResetTocFinder   ResetOperation = "toc_finder"
	ResetTocExtract  ResetOperation = "toc_extract"
	ResetTocLink     ResetOperation = "toc_link"
	ResetTocFinalize ResetOperation = "toc_finalize"
	ResetStructure   ResetOperation = "structure"
	ResetOcr         ResetOperation = "ocr"
)

// ValidResetOperations lists all valid reset operations.
var ValidResetOperations = []ResetOperation{
	ResetMetadata,
	ResetTocFinder,
	ResetTocExtract,
	ResetTocLink,
	ResetTocFinalize,
	ResetStructure,
	ResetOcr,
}

// IsValidResetOperation checks if an operation name is valid.
func IsValidResetOperation(op string) bool {
	for _, valid := range ValidResetOperations {
		if string(valid) == op {
			return true
		}
	}
	return false
}

// ResetFrom resets an operation and all its downstream dependencies.
// This enables re-running specific stages of the pipeline.
//
// Cascade dependencies are defined in OpRegistry.CascadesTo.
// OCR is a special case handled separately (not in OpRegistry).
func ResetFrom(ctx context.Context, book *BookState, tocDocID string, op ResetOperation) error {
	// Validate IDs to prevent GraphQL injection
	if err := defra.ValidateID(book.BookID); err != nil {
		return fmt.Errorf("invalid book ID: %w", err)
	}
	if tocDocID != "" {
		if err := defra.ValidateID(tocDocID); err != nil {
			return fmt.Errorf("invalid ToC doc ID: %w", err)
		}
	}

	// Ensure tocDocID is stored on book for OpConfig.DocIDSource
	if tocDocID != "" {
		book.SetTocDocID(tocDocID)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Debug("resetting operation with cascade", "operation", op, "book_id", book.BookID)
	}

	// OCR is a special case — not in the OpRegistry
	if op == ResetOcr {
		if err := resetAllOcr(ctx, book); err != nil {
			return err
		}
		// OCR reset cascades to ToC link and downstream operations
		return resetOpWithCascade(ctx, book, tocDocID, OpTocLink)
	}

	// Standard operations use the registry
	opType := OpType(op)
	if _, ok := OpRegistry[opType]; !ok {
		return fmt.Errorf("unknown reset operation: %s", op)
	}

	return resetOpWithCascade(ctx, book, tocDocID, opType)
}

// resetOpWithCascade resets an operation and recursively resets all downstream operations.
func resetOpWithCascade(ctx context.Context, book *BookState, tocDocID string, op OpType) error {
	cfg, ok := OpRegistry[op]
	if !ok {
		return fmt.Errorf("unknown operation: %s", op)
	}

	// Reset this operation
	if err := resetOp(ctx, book, tocDocID, op); err != nil {
		return err
	}

	// Cascade to downstream operations
	for _, downstream := range cfg.CascadesTo {
		if err := resetOpWithCascade(ctx, book, tocDocID, downstream); err != nil {
			return err
		}
	}

	return nil
}
