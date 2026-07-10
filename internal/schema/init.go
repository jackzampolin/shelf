package schema

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
)

type additiveField struct {
	Collection string
	Name       string
	Kind       int
}

// DefraDB does not merge an SDL into an existing collection. Additive changes
// must be explicit JSON Patches; keeping the list here makes startup migration
// idempotent and preserves all existing documents.
var requiredAdditiveFields = []additiveField{
	{Collection: "Job", Name: "status_reason", Kind: 11},
	{Collection: "Job", Name: "heartbeat_at", Kind: 10},
	{Collection: "Job", Name: "last_progress_at", Kind: 10},
	{Collection: "Page", Name: "ocr_quarantined", Kind: 2},
	{Collection: "Page", Name: "ocr_quarantine_reason", Kind: 11},
}

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
		} else {
			return fmt.Errorf("failed to add schemas: %w", err)
		}
	} else {
		logger.Info("schemas added", "names", schemaNames)
	}

	return ensureAdditiveFields(ctx, client, logger)
}

func ensureAdditiveFields(ctx context.Context, client *defra.Client, logger *slog.Logger) error {
	descriptions, err := client.ListCollectionDescriptions(ctx)
	if err != nil {
		return fmt.Errorf("failed to describe collections for migration: %w", err)
	}
	existing := make(map[string]map[string]struct{}, len(descriptions))
	for _, description := range descriptions {
		fields := make(map[string]struct{}, len(description.Fields))
		for _, field := range description.Fields {
			fields[field.Name] = struct{}{}
		}
		existing[description.Name] = fields
	}

	type patchValue struct {
		Name string `json:"Name"`
		Kind int    `json:"Kind"`
	}
	type patchOperation struct {
		Op    string     `json:"op"`
		Path  string     `json:"path"`
		Value patchValue `json:"value"`
	}
	operations := make([]patchOperation, 0, len(requiredAdditiveFields))
	var added []string
	for _, required := range requiredAdditiveFields {
		fields, collectionExists := existing[required.Collection]
		if !collectionExists {
			return fmt.Errorf("required collection %s is missing after schema initialization", required.Collection)
		}
		if _, fieldExists := fields[required.Name]; fieldExists {
			continue
		}
		operations = append(operations, patchOperation{
			Op:   "add",
			Path: "/" + required.Collection + "/Fields/-",
			Value: patchValue{
				Name: required.Name,
				Kind: required.Kind,
			},
		})
		added = append(added, required.Collection+"."+required.Name)
	}
	if len(operations) == 0 {
		return nil
	}

	patch, err := json.Marshal(operations)
	if err != nil {
		return fmt.Errorf("failed to encode additive schema migration: %w", err)
	}
	if err := client.PatchCollection(ctx, string(patch)); err != nil {
		return fmt.Errorf("failed to apply additive schema migration: %w", err)
	}
	logger.Info("applied additive schema migration", "fields", added)
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
