package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// loadBookMetadataFromDB loads book metadata from DefraDB.
// Returns (metadata, loaded). loaded is true when the query succeeded (even if metadata is nil).
func loadBookMetadataFromDB(ctx context.Context, bookID string) (*BookMetadata, bool) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		// No DefraDB client - expected in test contexts
		return nil, false
	}

	// Validate bookID to prevent GraphQL injection
	if err := defra.ValidateID(bookID); err != nil {
		return nil, false
	}

	logger := svcctx.LoggerFrom(ctx)

	query := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			title
			author
			isbn
			lccn
			publisher
			publication_year
			language
			description
		}
	}`, bookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		if logger != nil {
			logger.Error("book metadata query failed; metadata will be unavailable",
				"book_id", bookID, "error", err)
		}
		return nil, false
	}

	books, ok := resp.Data["Book"].([]any)
	if !ok || len(books) == 0 {
		return nil, true
	}

	bookData, ok := books[0].(map[string]any)
	if !ok {
		return nil, true
	}

	metadata := &BookMetadata{}

	if v, ok := bookData["title"].(string); ok {
		metadata.Title = v
	}
	if v, ok := bookData["author"].(string); ok {
		metadata.Author = v
	}
	if v, ok := bookData["isbn"].(string); ok {
		metadata.ISBN = v
	}
	if v, ok := bookData["lccn"].(string); ok {
		metadata.LCCN = v
	}
	if v, ok := bookData["publisher"].(string); ok {
		metadata.Publisher = v
	}
	if v, ok := bookData["publication_year"].(float64); ok {
		metadata.PublicationYear = int(v)
	}
	if v, ok := bookData["language"].(string); ok {
		metadata.Language = v
	}
	if v, ok := bookData["description"].(string); ok {
		metadata.Description = v
	}

	return metadata, true
}

// loadBookCostsFromDB loads cost data from Metric records for a book.
// Aggregates costs by stage and sets total on the BookState.
// NOTE: Caller must hold the write lock on BookState.
func loadBookCostsFromDB(ctx context.Context, book *BookState) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		// No DefraDB client - costs cannot be loaded but this is expected in test contexts
		return
	}

	logger := svcctx.LoggerFrom(ctx)

	// Query all metrics for this book
	query := fmt.Sprintf(`{
		Metric(filter: {book_id: {_eq: "%s"}}) {
			stage
			cost_usd
		}
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		if logger != nil {
			logger.Error("book costs query failed; cost data will be unavailable",
				"book_id", book.BookID, "error", err)
		}
		// Don't set costsLoaded=true on error - allows retry on next access
		return
	}

	metrics, ok := resp.Data["Metric"].([]any)
	if !ok || len(metrics) == 0 {
		book.costsLoaded = true
		return
	}

	// Aggregate costs by stage
	costsByStage := make(map[string]float64)
	var totalCost float64

	for _, m := range metrics {
		metric, ok := m.(map[string]any)
		if !ok {
			continue
		}

		var stage string
		var costUSD float64

		if s, ok := metric["stage"].(string); ok {
			stage = s
		}
		if c, ok := metric["cost_usd"].(float64); ok {
			costUSD = c
		}

		if stage != "" && costUSD > 0 {
			costsByStage[stage] += costUSD
			totalCost += costUSD
		}
	}

	book.costsByStage = costsByStage
	book.totalCost = totalCost
	book.costsLoaded = true

	if logger != nil {
		logger.Debug("loaded book costs",
			"book_id", book.BookID,
			"total_cost", totalCost,
			"stages", len(costsByStage))
	}
}

// loadAgentRunsFromDB loads agent run summaries from DefraDB for a book.
// NOTE: Caller must hold the write lock on BookState.
func loadAgentRunsFromDB(ctx context.Context, book *BookState) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		// No DefraDB client - agent runs cannot be loaded but this is expected in test contexts
		return
	}

	logger := svcctx.LoggerFrom(ctx)

	// Query all agent runs for this book
	query := fmt.Sprintf(`{
		AgentRun(filter: {book_id: {_eq: "%s"}}) {
			_docID
			agent_type
			job_id
			started_at
			completed_at
			iterations
			success
			error
		}
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		if logger != nil {
			logger.Error("agent run query failed; history will be unavailable",
				"book_id", book.BookID, "error", err)
		}
		// Don't set agentRunsLoaded=true on error - allows retry on next access
		return
	}

	runs, ok := resp.Data["AgentRun"].([]any)
	if !ok || len(runs) == 0 {
		book.agentRunsLoaded = true
		return
	}

	// Parse agent runs into summaries
	var summaries []AgentRunSummary
	for _, r := range runs {
		run, ok := r.(map[string]any)
		if !ok {
			continue
		}

		summary := AgentRunSummary{}

		if v, ok := run["_docID"].(string); ok {
			summary.DocID = v
		}
		if v, ok := run["agent_type"].(string); ok {
			summary.AgentType = v
		}
		if v, ok := run["job_id"].(string); ok {
			summary.JobID = v
		}
		if v, ok := run["started_at"].(string); ok {
			summary.StartedAt = v
		}
		if v, ok := run["completed_at"].(string); ok {
			summary.CompletedAt = v
		}
		if v, ok := run["iterations"].(float64); ok {
			summary.Iterations = int(v)
		}
		if v, ok := run["success"].(bool); ok {
			summary.Success = v
		}
		if v, ok := run["error"].(string); ok {
			summary.Error = v
		}

		if summary.DocID != "" {
			summaries = append(summaries, summary)
		}
	}

	book.agentRuns = summaries
	book.agentRunsLoaded = true

	if logger != nil {
		logger.Debug("loaded agent runs",
			"book_id", book.BookID,
			"count", len(summaries))
	}
}
