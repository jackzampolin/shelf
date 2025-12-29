package job

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/agents/toc_finder/tools"
	"github.com/jackzampolin/shelf/internal/providers"
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
		}`, j.BookID)
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
			result, err := sink.SendSync(ctx, defra.WriteOp{
				Collection: "ToC",
				Document: map[string]any{
					"toc_found":        false,
					"finder_complete":  false,
					"extract_complete": false,
					"link_complete":    false,
				},
				Op: defra.OpCreate,
			})
			if err != nil {
				return nil
			}
			j.TocDocID = result.DocID

			// Then update the Book to link to this ToC
			sink.Send(defra.WriteOp{
				Collection: "Book",
				DocID:      j.BookID,
				Document: map[string]any{
					"toc_id": j.TocDocID,
				},
				Op: defra.OpUpdate,
			})
		}
	}

	// Create tools for the agent
	tocTools := tools.New(tools.Config{
		BookID:      j.BookID,
		TotalPages:  j.TotalPages,
		DefraClient: defraClient,
		HomeDir:     j.HomeDir,
	})

	// Create agent
	userPrompt := toc_finder.BuildUserPrompt(j.BookID, j.TotalPages, nil)
	j.TocAgent = agent.New(agent.Config{
		Tools: tocTools,
		InitialMessages: []providers.Message{
			{Role: "system", Content: toc_finder.SystemPrompt},
			{Role: "user", Content: userPrompt},
		},
		MaxIterations: 15,
	})

	// Get first work unit from agent
	return j.getNextTocFinderWorkUnit()
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

		// Execute any tool calls synchronously (they're fast local operations)
		for {
			units := j.TocAgent.NextWorkUnits()
			if len(units) == 0 {
				break
			}

			// Check if it's a tool call
			if units[0].Type == agent.WorkUnitTypeTool {
				for _, unit := range units {
					if unit.ToolCall != nil {
						resultStr, err := j.TocAgent.ExecuteTool(ctx, *unit.ToolCall)
						j.TocAgent.HandleToolResult(unit.ToolCall.ID, resultStr, err)
					}
				}
			} else {
				// It's an LLM call, return as work unit
				return j.convertTocAgentUnits(units), nil
			}
		}
	}

	// Check if agent is done
	if j.TocAgent.IsDone() {
		j.BookState.TocFinderDone = true
		agentResult := j.TocAgent.Result()

		if agentResult != nil && agentResult.Success {
			// Save result to DefraDB
			if tocResult, ok := agentResult.ToolResult.(*toc_finder.Result); ok {
				if err := j.saveTocFinderResult(ctx, tocResult); err != nil {
					return nil, fmt.Errorf("failed to save ToC finder result: %w", err)
				}
				j.BookState.TocFound = tocResult.ToCFound
				if tocResult.ToCPageRange != nil {
					j.BookState.TocStartPage = tocResult.ToCPageRange.StartPage
					j.BookState.TocEndPage = tocResult.ToCPageRange.EndPage
				}
			}
		} else {
			// Agent failed or no ToC found - mark finder as done with no ToC
			j.BookState.TocFound = false
			sink := svcctx.DefraSinkFrom(ctx)
			if sink == nil {
				return nil, fmt.Errorf("defra sink not in context")
			}
			// Fire-and-forget - no need to block
			sink.Send(defra.WriteOp{
				Collection: "ToC",
				DocID:      j.TocDocID,
				Document: map[string]any{
					"toc_found":       false,
					"finder_complete": true,
				},
				Op: defra.OpUpdate,
			})
		}

		// Check if we should start ToC extraction
		return j.MaybeStartBookOperations(ctx), nil
	}

	// Get more work units from agent
	nextUnit := j.getNextTocFinderWorkUnit()
	if nextUnit == nil {
		return nil, nil
	}
	return []jobs.WorkUnit{*nextUnit}, nil
}

// getNextTocFinderWorkUnit gets the next work unit from the ToC finder agent.
// Must be called with j.Mu held.
func (j *Job) getNextTocFinderWorkUnit() *jobs.WorkUnit {
	if j.TocAgent == nil {
		return nil
	}
	units := j.TocAgent.NextWorkUnits()
	if len(units) == 0 {
		return nil
	}
	converted := j.convertTocAgentUnits(units)
	if len(converted) == 0 {
		return nil
	}
	return &converted[0]
}

// convertTocAgentUnits converts agent work units to job work units.
func (j *Job) convertTocAgentUnits(agentUnits []agent.WorkUnit) []jobs.WorkUnit {
	var units []jobs.WorkUnit
	for _, au := range agentUnits {
		if au.Type == agent.WorkUnitTypeLLM && au.ChatRequest != nil {
			unitID := uuid.New().String()
			j.RegisterWorkUnit(unitID, WorkUnitInfo{
				UnitType: "toc_finder",
			})

			metrics := j.MetricsFor()
			metrics.ItemKey = "toc_finder"

			units = append(units, jobs.WorkUnit{
				ID:          unitID,
				Type:        jobs.WorkUnitTypeLLM,
				Provider:    j.TocProvider,
				JobID:       j.RecordID,
				ChatRequest: au.ChatRequest,
				Tools:       au.Tools,
				Metrics:     metrics,
			})
		}
	}
	return units
}

// saveTocFinderResult saves the ToC finder result to DefraDB.
func (j *Job) saveTocFinderResult(ctx context.Context, result *toc_finder.Result) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	update := map[string]any{
		"toc_found":       result.ToCFound,
		"finder_complete": true,
	}

	if result.ToCPageRange != nil {
		update["start_page"] = result.ToCPageRange.StartPage
		update["end_page"] = result.ToCPageRange.EndPage
	}

	if result.StructureSummary != nil {
		summaryJSON, err := json.Marshal(result.StructureSummary)
		if err == nil {
			update["structure_summary"] = string(summaryJSON)
		}
	}

	// Fire-and-forget - no need to block
	sink.Send(defra.WriteOp{
		Collection: "ToC",
		DocID:      j.TocDocID,
		Document:   update,
		Op:         defra.OpUpdate,
	})
	return nil
}
