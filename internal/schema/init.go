package schema

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"sort"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
)

type additiveField struct {
	Collection string
	Name       string
	Kind       int
	Typ        int
}

// DefraDB does not merge an SDL into an existing collection. Additive changes
// must be explicit JSON Patches; keeping the list here makes startup migration
// idempotent and preserves all existing documents.
var requiredAdditiveFields = []additiveField{
	{Collection: "Job", Name: "status_reason", Kind: 11, Typ: 1},
	{Collection: "Job", Name: "heartbeat_at", Kind: 10, Typ: 1},
	{Collection: "Job", Name: "last_progress_at", Kind: 10, Typ: 1},
	{Collection: "Book", Name: "source_format", Kind: 11, Typ: 1},
	{Collection: "Book", Name: "source_filename", Kind: 11, Typ: 1},
	{Collection: "Book", Name: "source_sha256", Kind: 11, Typ: 1},
	{Collection: "Book", Name: "source_identifier", Kind: 11, Typ: 1},
	{Collection: "Book", Name: "source_imported_at", Kind: 10, Typ: 1},
	{Collection: "Page", Name: "ocr_quarantined", Kind: 2, Typ: 1},
	{Collection: "Page", Name: "ocr_quarantine_reason", Kind: 11, Typ: 1},
	{Collection: "ToC", Name: "finder_override", Kind: 2, Typ: 1},
	{Collection: "ToC", Name: "finder_override_reason", Kind: 11, Typ: 1},
	{Collection: "ToC", Name: "finder_override_at", Kind: 10, Typ: 1},
	{Collection: "TocEntry", Name: "link_retries", Kind: 4, Typ: 1},
	{Collection: "TocEntry", Name: "link_failed", Kind: 2, Typ: 1},
	{Collection: "TocEntry", Name: "link_failure_reason", Kind: 11, Typ: 1},
	{Collection: "TocEntry", Name: "link_failed_at", Kind: 10, Typ: 1},
	{Collection: "TocEntry", Name: "link_repair_reason", Kind: 11, Typ: 1},
	{Collection: "TocEntry", Name: "link_repaired_at", Kind: 10, Typ: 1},
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
	type existingField struct {
		Index int
		Typ   int
	}
	existing := make(map[string]map[string]existingField, len(descriptions))
	for _, description := range descriptions {
		fields := make(map[string]existingField, len(description.Fields))
		for index, field := range description.Fields {
			fields[field.Name] = existingField{Index: index, Typ: field.Typ}
		}
		existing[description.Name] = fields
	}

	type patchValue struct {
		Name string `json:"Name"`
		Kind int    `json:"Kind"`
		Typ  int    `json:"Typ"`
	}
	type patchOperation struct {
		Op    string `json:"op"`
		Path  string `json:"path"`
		Value any    `json:"value,omitempty"`
	}
	type malformedField struct {
		Required additiveField
		Index    int
	}
	var malformed []malformedField
	var additions []patchOperation
	var added []string
	for _, required := range requiredAdditiveFields {
		fields, collectionExists := existing[required.Collection]
		if !collectionExists {
			return fmt.Errorf("required collection %s is missing after schema initialization", required.Collection)
		}
		if field, fieldExists := fields[required.Name]; fieldExists {
			if field.Typ != required.Typ {
				malformed = append(malformed, malformedField{Required: required, Index: field.Index})
				added = append(added, required.Collection+"."+required.Name+".Typ")
			}
			continue
		}
		additions = append(additions, patchOperation{
			Op:   "add",
			Path: "/" + required.Collection + "/Fields/-",
			Value: patchValue{
				Name: required.Name,
				Kind: required.Kind,
				Typ:  required.Typ,
			},
		})
		added = append(added, required.Collection+"."+required.Name)
	}

	// DefraDB rejects in-place field mutations. A Typ=0 additive field cannot
	// have stored values, so repair it by removing the malformed definition and
	// adding it back with the scalar CRDT type. Remove descending indexes first
	// so earlier removals do not shift later JSON Patch paths.
	sort.Slice(malformed, func(i, j int) bool {
		if malformed[i].Required.Collection == malformed[j].Required.Collection {
			return malformed[i].Index > malformed[j].Index
		}
		return malformed[i].Required.Collection < malformed[j].Required.Collection
	})
	operations := make([]patchOperation, 0, len(malformed)*2+len(additions))
	for _, field := range malformed {
		operations = append(operations, patchOperation{
			Op:   "remove",
			Path: fmt.Sprintf("/%s/Fields/%d", field.Required.Collection, field.Index),
		})
	}
	for _, field := range malformed {
		operations = append(operations, patchOperation{
			Op:   "add",
			Path: "/" + field.Required.Collection + "/Fields/-",
			Value: patchValue{
				Name: field.Required.Name,
				Kind: field.Required.Kind,
				Typ:  field.Required.Typ,
			},
		})
	}
	operations = append(operations, additions...)
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
