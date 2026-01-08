package job

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateClassifyWorkUnit creates an LLM work unit for matter classification.
// This is a single call that classifies all chapters at once.
func (j *Job) CreateClassifyWorkUnit(ctx context.Context) (*jobs.WorkUnit, error) {
	// Get system prompt (with possible book-level override)
	systemPrompt := j.Book.GetPrompt(PromptKeyClassifySystem)
	if systemPrompt == "" {
		systemPrompt = ClassifySystemPrompt
	}

	// Build user prompt with all chapters
	userPrompt := BuildClassifyPrompt(j.Chapters)

	// Create JSON schema for structured output
	schemaBytes, err := json.Marshal(ClassifyJSONSchema())
	if err != nil {
		return nil, fmt.Errorf("failed to marshal JSON schema: %w", err)
	}

	responseFormat := &providers.ResponseFormat{
		Type:       "json_schema",
		JSONSchema: schemaBytes,
	}

	request := &providers.ChatRequest{
		Model: "", // Will be set by scheduler based on provider
		Messages: []providers.Message{
			{Role: "system", Content: systemPrompt},
			{Role: "user", Content: userPrompt},
		},
		ResponseFormat: responseFormat,
	}

	// Create work unit
	unitID := uuid.New().String()
	unit := &jobs.WorkUnit{
		ID:          unitID,
		Type:        jobs.WorkUnitTypeLLM,
		Provider:    j.Book.TocProvider, // Reuse ToC provider for structure work
		JobID:       j.RecordID,
		ChatRequest: request,
		Metrics: &jobs.WorkUnitMetrics{
			Stage:     j.Type(),
			ItemKey:   "classify_matter",
			PromptKey: PromptKeyClassifySystem,
			PromptCID: j.Book.GetPromptCID(PromptKeyClassifySystem),
			BookID:    j.Book.BookID,
		},
	}

	// Register work unit
	j.Tracker.Register(unitID, WorkUnitInfo{
		UnitType: WorkUnitTypeClassify,
		Phase:    PhaseClassify,
	})

	j.ClassifyPending = true
	return unit, nil
}

// ProcessClassifyResult parses and applies classification results.
func (j *Job) ProcessClassifyResult(ctx context.Context, result jobs.WorkResult) error {
	logger := svcctx.LoggerFrom(ctx)

	if result.ChatResult == nil {
		return fmt.Errorf("no chat result")
	}

	// Parse JSON response
	var content []byte
	if len(result.ChatResult.ParsedJSON) > 0 {
		content = result.ChatResult.ParsedJSON
	} else if result.ChatResult.Content != "" {
		content = []byte(result.ChatResult.Content)
	} else {
		return fmt.Errorf("empty response")
	}

	var classifyResult ClassifyResult
	if err := json.Unmarshal(content, &classifyResult); err != nil {
		return fmt.Errorf("failed to parse classification result: %w", err)
	}

	// Store classifications
	j.Classifications = classifyResult.Classifications

	// Apply to chapters
	for _, chapter := range j.Chapters {
		if matterType, ok := j.Classifications[chapter.EntryID]; ok {
			chapter.MatterType = matterType
		}
	}

	if logger != nil {
		logger.Info("applied matter classifications",
			"book_id", j.Book.BookID,
			"classifications", len(j.Classifications))
	}

	j.ClassifyPending = false
	return nil
}

// PersistClassifyResults persists classification results to DefraDB.
func (j *Job) PersistClassifyResults(ctx context.Context) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	for _, chapter := range j.Chapters {
		if chapter.DocID == "" {
			continue
		}

		// Update chapter with matter_type
		sink.Send(defra.WriteOp{
			Collection: "Chapter",
			DocID:      chapter.DocID,
			Document: map[string]any{
				"matter_type": chapter.MatterType,
			},
			Op: defra.OpUpdate,
		})
	}

	return nil
}
