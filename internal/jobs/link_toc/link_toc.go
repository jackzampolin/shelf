package link_toc

import (
	"context"
	"fmt"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	ljob "github.com/jackzampolin/shelf/internal/jobs/link_toc/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "link-toc"

// Config configures the link toc job.
type Config struct {
	TocProvider string
	DebugAgents bool
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if c.TocProvider == "" {
		return fmt.Errorf("toc provider is required")
	}
	return nil
}

// NewJob creates a new link toc job for the given book.
func NewJob(ctx context.Context, cfg Config, bookID string) (jobs.Job, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("invalid config: %w", err)
	}

	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		return nil, fmt.Errorf("home directory not in context")
	}

	// Load everything about this book
	result, err := common.LoadBook(ctx, bookID, common.LoadBookConfig{
		HomeDir:     homeDir,
		TocProvider: cfg.TocProvider,
		DebugAgents: cfg.DebugAgents,
		PromptKeys:  ljob.PromptKeys(),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to load book: %w", err)
	}

	// Verify preconditions: ToC extraction must be complete
	if !result.Book.TocExtract.IsComplete() {
		return nil, fmt.Errorf("ToC extraction not complete - cannot link entries")
	}

	// Load TocEntry records
	entries, err := LoadTocEntries(ctx, result.TocDocID)
	if err != nil {
		return nil, fmt.Errorf("failed to load ToC entries: %w", err)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("creating link toc job",
			"book_id", bookID,
			"total_pages", result.Book.TotalPages,
			"toc_provider", cfg.TocProvider,
			"entries_count", len(entries))
	}

	return ljob.NewFromLoadResult(result, entries), nil
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
func JobFactory(cfg Config) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		return NewJob(ctx, cfg, bookID)
	})
}

// LoadTocEntries loads all TocEntry records for a ToC.
func LoadTocEntries(ctx context.Context, tocDocID string) ([]*toc_entry_finder.TocEntry, error) {
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

	var entries []*toc_entry_finder.TocEntry
	for _, e := range rawEntries {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}

		// Skip entries that already have actual_page linked
		if actualPage, ok := entry["actual_page"].(map[string]any); ok {
			if _, hasDoc := actualPage["_docID"]; hasDoc {
				continue // Already linked
			}
		}

		te := &toc_entry_finder.TocEntry{}

		if docID, ok := entry["_docID"].(string); ok {
			te.DocID = docID
		}
		if entryNum, ok := entry["entry_number"].(string); ok {
			te.EntryNumber = entryNum
		}
		if title, ok := entry["title"].(string); ok {
			te.Title = title
		}
		if level, ok := entry["level"].(float64); ok {
			te.Level = int(level)
		}
		if levelName, ok := entry["level_name"].(string); ok {
			te.LevelName = levelName
		}
		if printedPage, ok := entry["printed_page_number"].(string); ok {
			te.PrintedPageNumber = printedPage
		}
		if sortOrder, ok := entry["sort_order"].(float64); ok {
			te.SortOrder = int(sortOrder)
		}

		if te.DocID != "" {
			entries = append(entries, te)
		}
	}

	return entries, nil
}
