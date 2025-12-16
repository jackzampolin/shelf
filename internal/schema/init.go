package schema

import (
	"context"
	"fmt"
	"log/slog"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
)

// Initialize applies all schemas to DefraDB.
// It's safe to call multiple times - existing schemas are skipped.
func Initialize(ctx context.Context, client *defra.Client, logger *slog.Logger) error {
	schemas, err := All()
	if err != nil {
		return fmt.Errorf("failed to load schemas: %w", err)
	}

	for _, s := range schemas {
		if err := applySchema(ctx, client, s, logger); err != nil {
			return err
		}
	}

	return nil
}

// applySchema adds a single schema to DefraDB.
// Returns nil if schema already exists.
func applySchema(ctx context.Context, client *defra.Client, s Schema, logger *slog.Logger) error {
	err := client.AddSchema(ctx, s.SDL)
	if err != nil {
		// Check if it's an "already exists" error - that's fine
		if isAlreadyExistsError(err) {
			logger.Info("schema already exists", "name", s.Name)
			return nil
		}
		return fmt.Errorf("failed to add schema %s: %w", s.Name, err)
	}

	logger.Info("schema added", "name", s.Name)
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
