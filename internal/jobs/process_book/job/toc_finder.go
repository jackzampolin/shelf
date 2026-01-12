package job

import (
	"context"
	"fmt"
	"time"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateTocFinderWorkUnit creates a ToC finder agent work unit.
// Must be called with j.Mu held.
func (j *Job) CreateTocFinderWorkUnit(ctx context.Context) *jobs.WorkUnit {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return nil
	}
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil
	}

	// Create or get ToC record
	// Note: The Book->ToC relationship has @primary on Book side,
	// so we create ToC first, then link it to Book via toc_id
	if j.TocDocID == "" {
		// First, check if Book already has a ToC linked
		query := fmt.Sprintf(`{
			Book(filter: {_docID: {_eq: "%s"}}) {
				toc {
					_docID
				}
			}
		}`, j.Book.BookID)
		resp, err := defraClient.Execute(ctx, query, nil)
		if err == nil {
			if books, ok := resp.Data["Book"].([]any); ok && len(books) > 0 {
				if book, ok := books[0].(map[string]any); ok {
					if toc, ok := book["toc"].(map[string]any); ok {
						if docID, ok := toc["_docID"].(string); ok && docID != "" {
							j.TocDocID = docID
						}
					}
				}
			}
		}

		// Only create if no ToC exists
		if j.TocDocID == "" {
			// Include created_at timestamp to ensure unique DocID per book/attempt
			// (DefraDB generates deterministic DocIDs based on content)
			result, err := sink.SendSync(ctx, defra.WriteOp{
				Collection: "ToC",
				Document: map[string]any{
					"toc_found":        false,
					"finder_complete":  false,
					"extract_complete": false,
					"link_started":     false,
					"link_complete":    false,
					"link_failed":      false,
					"link_retries":     0,
					"finder_started":   true,
					"created_at":       time.Now().Format(time.RFC3339Nano),
				},
				Op: defra.OpCreate,
			})
			if err != nil {
				return nil
			}
			j.TocDocID = result.DocID

			// Update the Book to link to this ToC synchronously to ensure
			// the relationship exists before we return
			_, err = sink.SendSync(ctx, defra.WriteOp{
				Collection: "Book",
				DocID:      j.Book.BookID,
				Document: map[string]any{
					"toc_id": j.TocDocID,
				},
				Op: defra.OpUpdate,
			})
			if err != nil {
				// Log but continue - ToC was created, just not linked yet
				logger := svcctx.LoggerFrom(ctx)
				if logger != nil {
					logger.Warn("failed to link ToC to Book", "error", err, "toc_doc_id", j.TocDocID)
				}
			}
		}
	}

	// Create agent via factory (passing context for observability logging)
	j.TocAgent = agents.NewTocFinderAgent(ctx, agents.TocFinderConfig{
		Book:         j.Book,
		SystemPrompt: j.GetPrompt(toc_finder.PromptKey),
		Debug:        j.Book.DebugAgents,
		JobID:        j.RecordID,
	})

	// Get first work unit using helper
	agentUnits := agents.ExecuteToolLoop(ctx, j.TocAgent)
	if len(agentUnits) == 0 {
		return nil
	}

	// Convert and return first work unit
	jobUnits := j.convertTocAgentUnits(agentUnits)
	if len(jobUnits) == 0 {
		return nil
	}
	return &jobUnits[0]
}

// HandleTocFinderComplete processes ToC finder agent work unit completion.
// Must be called with j.Mu held.
func (j *Job) HandleTocFinderComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	if j.TocAgent == nil {
		return nil, fmt.Errorf("toc agent not initialized")
	}

	// Handle LLM result
	if result.ChatResult != nil {
		j.TocAgent.HandleLLMResult(result.ChatResult)

		// Execute tool loop using helper
		agentUnits := agents.ExecuteToolLoop(ctx, j.TocAgent)
		if len(agentUnits) > 0 {
			// It's an LLM call, return as work unit
			return j.convertTocAgentUnits(agentUnits), nil
		}
	}

	// Check if agent is done
	if j.TocAgent.IsDone() {
		// Save agent log if debug enabled
		if err := j.TocAgent.SaveLog(ctx); err != nil {
			logger := svcctx.LoggerFrom(ctx)
			if logger != nil {
				logger.Warn("failed to save agent log", "error", err)
			}
		}

		j.Book.TocFinder.Complete()
		agentResult := j.TocAgent.Result()

		if agentResult != nil && agentResult.Success {
			// Save result to DefraDB
			if tocResult, ok := agentResult.ToolResult.(*toc_finder.Result); ok {
				if err := common.SaveTocFinderResult(ctx, j.TocDocID, tocResult); err != nil {
					return nil, fmt.Errorf("failed to save ToC finder result: %w", err)
				}
				// Update in-memory state using thread-safe accessor
				if tocResult.ToCPageRange != nil {
					j.Book.SetTocResult(tocResult.ToCFound, tocResult.ToCPageRange.StartPage, tocResult.ToCPageRange.EndPage)
				} else {
					j.Book.SetTocFound(tocResult.ToCFound)
				}
			}
		} else {
			// Agent failed or no ToC found - mark finder as done with no ToC
			j.Book.SetTocFound(false)
			if err := common.SaveTocFinderNoResult(ctx, j.TocDocID); err != nil {
				return nil, err
			}
		}

		// Check if we should start ToC extraction
		return j.MaybeStartBookOperations(ctx), nil
	}

	// Agent not done but no LLM work units - shouldn't happen
	return nil, nil
}

// convertTocAgentUnits converts agent work units to job work units.
func (j *Job) convertTocAgentUnits(agentUnits []agent.WorkUnit) []jobs.WorkUnit {
	jobUnits := agents.ConvertToJobUnits(agentUnits, agents.ConvertConfig{
		JobID:     j.RecordID,
		Provider:  j.Book.TocProvider,
		Stage:     "toc",
		ItemKey:   "toc_finder",
		PromptKey: toc_finder.PromptKey,
		PromptCID: j.GetPromptCID(toc_finder.PromptKey),
		BookID:    j.Book.BookID,
	})

	// Register work units (Job keeps tracking)
	for _, u := range jobUnits {
		j.RegisterWorkUnit(u.ID, WorkUnitInfo{UnitType: WorkUnitTypeTocFinder})
	}

	return jobUnits
}
