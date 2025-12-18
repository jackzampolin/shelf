package schema

import (
	"context"
	"fmt"
	"log/slog"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
)

// Initialize applies all schemas to DefraDB.
// All schemas are combined into a single SDL to handle circular dependencies
// (e.g., Book references Page, Page references Book).
// It's safe to call multiple times - existing schemas are skipped.
func Initialize(ctx context.Context, client *defra.Client, logger *slog.Logger) error {
	schemas, err := All()
	if err != nil {
		return fmt.Errorf("failed to load schemas: %w", err)
	}

	// Combine all schemas into one SDL to handle circular dependencies
	var sdlParts []string
	var schemaNames []string
	for _, s := range schemas {
		sdlParts = append(sdlParts, s.SDL)
		schemaNames = append(schemaNames, s.Name)
	}
	combinedSDL := strings.Join(sdlParts, "\n\n")

	// Add all schemas in one call
	err = client.AddSchema(ctx, combinedSDL)
	if err != nil {
		if isAlreadyExistsError(err) {
			logger.Info("schemas already exist", "names", schemaNames)
			return nil
		}
		return fmt.Errorf("failed to add schemas: %w", err)
	}

	logger.Info("schemas added", "names", schemaNames)
	return nil
}

// isAlreadyExistsError checks if the error indicates the collection already exists.
// Note: DefraDB is accessed via HTTP API, not a Go SDK, so errors are parsed from
// response bodies. String matching is unavoidable here.
func isAlreadyExistsError(err error) bool {
	if err == nil {
		return false
	}
	msg := err.Error()
	return strings.Contains(msg, "collection already exists") ||
		strings.Contains(msg, "already exists")
}
