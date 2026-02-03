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

// AgentTypeTocFinder is the agent type identifier for ToC finder agents.
// Uses the centralized constant from common.AgentTypeTocFinder.
const AgentTypeTocFinder = common.AgentTypeTocFinder

// CreateTocFinderWorkUnit creates a ToC finder agent work unit.
// Must be called with j.Mu held.
func (j *Job) CreateTocFinderWorkUnit(ctx context.Context) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		if logger != nil {
			logger.Error("CreateTocFinderWorkUnit: defra client not in context - check service initialization",
				"book_id", j.Book.BookID)
		}
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
			result, err := common.SendTracked(ctx, j.Book, defra.WriteOp{
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
				if logger != nil {
					logger.Warn("failed to create ToC record", "error", err)
				}
				return nil
			}
			j.TocDocID = result.DocID
			j.Book.SetTocDocID(j.TocDocID)
			if result.CID != "" {
				j.Book.SetTocCID(result.CID)
			}

			// Update the Book to link to this ToC synchronously to ensure
			// the relationship exists before we return
			_, err = common.SendTracked(ctx, j.Book, defra.WriteOp{
				Collection: "Book",
				DocID:      j.Book.BookID,
				Document: map[string]any{
					"toc_id": j.TocDocID,
				},
				Op: defra.OpUpdate,
			})
			if err != nil {
				// Log but continue - ToC was created, just not linked yet
				if logger != nil {
					logger.Warn("failed to link ToC to Book", "error", err, "toc_doc_id", j.TocDocID)
				}
			}
		}
	}
	if j.TocDocID != "" {
		j.Book.SetTocDocID(j.TocDocID)
	}

	// Check for saved agent state (job resume case)
	savedState := j.Book.GetAgentState(AgentTypeTocFinder, "")
	if savedState != nil && !savedState.Complete {
		// Resume existing agent
		if logger != nil {
			logger.Info("resuming ToC finder agent from saved state",
				"agent_id", savedState.AgentID,
				"iteration", savedState.Iteration)
		}

		// Create agent with fresh tools but restore conversation state
		j.TocAgent = agents.NewTocFinderAgent(ctx, agents.TocFinderConfig{
			Book:         j.Book,
			SystemPrompt: j.GetPrompt(toc_finder.PromptKey),
			Debug:        j.Book.DebugAgents,
			JobID:        j.RecordID,
		})

		// Restore state from saved
		if err := j.TocAgent.RestoreState(&agent.StateExport{
			AgentID:          savedState.AgentID,
			Iteration:        savedState.Iteration,
			Complete:         savedState.Complete,
			MessagesJSON:     savedState.MessagesJSON,
			PendingToolCalls: savedState.PendingToolCalls,
			ToolResults:      savedState.ToolResults,
			ResultJSON:       savedState.ResultJSON,
		}); err != nil {
			if logger != nil {
				logger.Warn("failed to restore ToC finder agent state, starting fresh", "error", err)
			}
			// Fall through to create fresh agent
			j.TocAgent = nil
		}
	}

	// Create fresh agent if not restored
	if j.TocAgent == nil {
		j.TocAgent = agents.NewTocFinderAgent(ctx, agents.TocFinderConfig{
			Book:         j.Book,
			SystemPrompt: j.GetPrompt(toc_finder.PromptKey),
			Debug:        j.Book.DebugAgents,
			JobID:        j.RecordID,
		})

		// Persist initial agent state (async, fire-and-forget)
		exported, _ := j.TocAgent.ExportState()
		initialState := &common.AgentState{
			AgentID:          exported.AgentID,
			AgentType:        common.AgentTypeTocFinder,
			EntryDocID:       "",
			Iteration:        exported.Iteration,
			Complete:         false,
			MessagesJSON:     exported.MessagesJSON,
			PendingToolCalls: exported.PendingToolCalls,
			ToolResults:      exported.ToolResults,
			ResultJSON:       "",
		}
		if err := common.PersistAgentState(ctx, j.Book, initialState); err != nil {
			if logger != nil {
				logger.Warn("failed to persist toc finder agent state", "error", err)
			}
		}
		j.Book.SetAgentState(initialState)
	}

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

	logger := svcctx.LoggerFrom(ctx)

	// Handle LLM result
	if result.ChatResult != nil {
		j.TocAgent.HandleLLMResult(result.ChatResult)

		// Note: No intermediate state persistence - crash recovery restarts from scratch
		// This eliminates the SendSync bottleneck that serialized agent execution

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
			if logger != nil {
				logger.Warn("failed to save agent log", "error", err)
			}
		}

		// Clean up agent state from BookState and DB
		j.cleanupTocFinderAgentState(ctx)

		j.Book.TocFinderComplete()
		agentResult := j.TocAgent.Result()

		if agentResult != nil && agentResult.Success {
			// Save result to DefraDB
			if tocResult, ok := agentResult.ToolResult.(*toc_finder.Result); ok {
				cid, err := common.SaveTocFinderResult(ctx, j.TocDocID, tocResult)
				if err != nil {
					return nil, fmt.Errorf("failed to save ToC finder result: %w", err)
				}
				if cid != "" {
					j.Book.SetTocCID(cid)
					j.Book.SetOperationCID(common.OpTocFinder, cid)
				}
				if err := common.UpdateMetricOutputRef(ctx, result.MetricDocID, "ToC", j.TocDocID, cid); err != nil {
					if logger != nil {
						logger.Warn("failed to update metric output ref", "error", err)
					}
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
			cid, err := common.SaveTocFinderNoResult(ctx, j.TocDocID)
			if err != nil {
				return nil, err
			}
			if cid != "" {
				j.Book.SetTocCID(cid)
				j.Book.SetOperationCID(common.OpTocFinder, cid)
			}
			if err := common.UpdateMetricOutputRef(ctx, result.MetricDocID, "ToC", j.TocDocID, cid); err != nil {
				if logger != nil {
					logger.Warn("failed to update metric output ref", "error", err)
				}
			}
		}

		// Check if we should start ToC extraction
		return j.MaybeStartBookOperations(ctx), nil
	}

	// Agent not done but no LLM work units - shouldn't happen
	return nil, nil
}

// cleanupTocFinderAgentState removes ToC finder agent state after completion.
func (j *Job) cleanupTocFinderAgentState(ctx context.Context) {
	logger := svcctx.LoggerFrom(ctx)
	existing := j.Book.GetAgentState(AgentTypeTocFinder, "")
	if existing != nil && existing.AgentID != "" {
		// Delete by agent_id since we don't have DocID from async create
		if err := common.DeleteAgentStateByAgentID(ctx, existing.AgentID); err != nil {
			if logger != nil {
				logger.Error("failed to delete agent state from DB, orphaned record remains",
					"agent_id", existing.AgentID,
					"agent_type", AgentTypeTocFinder,
					"book_id", j.Book.BookID,
					"error", err)
			}
		}
	}
	j.Book.RemoveAgentState(AgentTypeTocFinder, "")
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
