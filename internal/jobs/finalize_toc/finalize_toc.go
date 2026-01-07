package finalize_toc

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	fjob "github.com/jackzampolin/shelf/internal/jobs/finalize_toc/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "finalize-toc"

// Config configures the finalize toc job.
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

// NewJob creates a new finalize toc job for the given book.
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
		TocProvider: cfg.TocProvider,
		DebugAgents: cfg.DebugAgents,
		PromptKeys:  fjob.PromptKeys(),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to load book: %w", err)
	}

	// Verify preconditions: link_toc must be complete
	if !result.Book.TocLink.IsComplete() {
		return nil, fmt.Errorf("ToC linking not complete - cannot finalize")
	}

	// Load linked entries
	entries, err := LoadLinkedEntries(ctx, result.TocDocID)
	if err != nil {
		return nil, fmt.Errorf("failed to load linked entries: %w", err)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		linkedCount := 0
		for _, e := range entries {
			if e.ActualPage != nil {
				linkedCount++
			}
		}
		logger.Info("creating finalize toc job",
			"book_id", bookID,
			"total_pages", result.Book.TotalPages,
			"toc_provider", cfg.TocProvider,
			"entries_count", len(entries),
			"linked_count", linkedCount)
	}

	return fjob.NewFromLoadResult(result, entries), nil
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
func JobFactory(cfg Config) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		return NewJob(ctx, cfg, bookID)
	})
}

// LoadLinkedEntries loads all TocEntry records with their page links.
func LoadLinkedEntries(ctx context.Context, tocDocID string) ([]*fjob.LinkedTocEntry, error) {
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

	var entries []*fjob.LinkedTocEntry
	for _, e := range rawEntries {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}

		le := &fjob.LinkedTocEntry{}

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

// LoadCandidateHeadings loads heading candidates from Page.headings field.
func LoadCandidateHeadings(ctx context.Context, bookID string, bodyStart, bodyEnd int) ([]*fjob.CandidateHeading, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, page_num: {_gte: %d, _lte: %d}}) {
			page_num
			headings
		}
	}`, bookID, bodyStart, bodyEnd)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	rawPages, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil, nil
	}

	var candidates []*fjob.CandidateHeading
	for _, p := range rawPages {
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}

		pageNum := 0
		if pn, ok := page["page_num"].(float64); ok {
			pageNum = int(pn)
		}

		headings, ok := page["headings"].([]any)
		if !ok {
			continue
		}

		for _, h := range headings {
			heading, ok := h.(map[string]any)
			if !ok {
				continue
			}

			text, _ := heading["text"].(string)
			level := 0
			if lv, ok := heading["level"].(float64); ok {
				level = int(lv)
			}

			if text != "" {
				candidates = append(candidates, &fjob.CandidateHeading{
					PageNum: pageNum,
					Text:    text,
					Level:   level,
				})
			}
		}
	}

	return candidates, nil
}
