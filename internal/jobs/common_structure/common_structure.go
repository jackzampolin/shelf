package common_structure

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	csjob "github.com/jackzampolin/shelf/internal/jobs/common_structure/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "common-structure"

// Config configures the common structure job.
type Config struct {
	StructureProvider string
	DebugAgents       bool
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if c.StructureProvider == "" {
		return fmt.Errorf("structure provider is required")
	}
	return nil
}

// NewJob creates a new common structure job for the given book.
func NewJob(ctx context.Context, cfg Config, bookID string) (jobs.Job, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("invalid config: %w", err)
	}

	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		return nil, fmt.Errorf("home directory not in context")
	}

	// Load book info
	result, err := common.LoadBook(ctx, bookID, common.LoadBookConfig{
		HomeDir:     homeDir,
		TocProvider: cfg.StructureProvider,
		DebugAgents: cfg.DebugAgents,
		PromptKeys:  csjob.PromptKeys(),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to load book: %w", err)
	}

	// Verify preconditions: finalize_toc must be complete
	if !result.Book.TocFinalize.IsComplete() {
		return nil, fmt.Errorf("ToC finalization not complete - cannot build structure")
	}

	// Load linked entries (all should have actual_page after finalize_toc)
	entries, err := LoadFinalizedEntries(ctx, result.TocDocID)
	if err != nil {
		return nil, fmt.Errorf("failed to load finalized entries: %w", err)
	}

	if len(entries) == 0 {
		return nil, fmt.Errorf("no ToC entries found for book %s", bookID)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		linkedCount := 0
		for _, e := range entries {
			if e.ActualPage != nil {
				linkedCount++
			}
		}
		logger.Info("creating common structure job",
			"book_id", bookID,
			"total_pages", result.Book.TotalPages,
			"structure_provider", cfg.StructureProvider,
			"entries_count", len(entries),
			"linked_count", linkedCount)
	}

	return csjob.NewFromLoadResult(result, entries), nil
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
func JobFactory(cfg Config) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		return NewJob(ctx, cfg, bookID)
	})
}

// LoadFinalizedEntries loads all TocEntry records with their page links.
// After finalize_toc, all entries should have actual_page populated.
func LoadFinalizedEntries(ctx context.Context, tocDocID string) ([]*csjob.LinkedTocEntry, error) {
	if tocDocID == "" {
		return nil, fmt.Errorf("ToC document ID is required")
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		TocEntry(filter: {toc_id: {_eq: "%s"}}, order: {sort_order: ASC}) {
			_docID
			entry_number
			title
			level
			level_name
			printed_page_number
			sort_order
			actual_page {
				_docID
				page_num
			}
		}
	}`, tocDocID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	rawEntries, ok := resp.Data["TocEntry"].([]any)
	if !ok {
		return nil, nil // No entries
	}

	var entries []*csjob.LinkedTocEntry
	for _, e := range rawEntries {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}

		le := &csjob.LinkedTocEntry{}

		if docID, ok := entry["_docID"].(string); ok {
			le.DocID = docID
		}
		if entryNum, ok := entry["entry_number"].(string); ok {
			le.EntryNumber = entryNum
		}
		if title, ok := entry["title"].(string); ok {
			le.Title = title
		}
		if level, ok := entry["level"].(float64); ok {
			le.Level = int(level)
		}
		if levelName, ok := entry["level_name"].(string); ok {
			le.LevelName = levelName
		}
		if printedPage, ok := entry["printed_page_number"].(string); ok {
			le.PrintedPageNumber = printedPage
		}
		if sortOrder, ok := entry["sort_order"].(float64); ok {
			le.SortOrder = int(sortOrder)
		}

		// Extract actual_page link
		if actualPage, ok := entry["actual_page"].(map[string]any); ok {
			if pageDocID, ok := actualPage["_docID"].(string); ok {
				le.ActualPageDocID = pageDocID
			}
			if pageNum, ok := actualPage["page_num"].(float64); ok {
				pn := int(pageNum)
				le.ActualPage = &pn
			}
		}

		if le.DocID != "" {
			entries = append(entries, le)
		}
	}

	return entries, nil
}
