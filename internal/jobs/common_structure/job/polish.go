package job

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreatePolishWorkUnits creates LLM work units for polishing each chapter.
func (j *Job) CreatePolishWorkUnits(ctx context.Context) ([]jobs.WorkUnit, error) {
	var units []jobs.WorkUnit

	for _, chapter := range j.Chapters {
		if chapter.PolishDone {
			continue
		}

		// Skip if no text to polish
		if chapter.MechanicalText == "" {
			chapter.PolishDone = true
			chapter.PolishedText = ""
			continue
		}

		unit, err := j.createPolishWorkUnit(ctx, chapter)
		if err != nil {
			if logger := svcctx.LoggerFrom(ctx); logger != nil {
				logger.Warn("failed to create polish work unit",
					"chapter", chapter.EntryID,
					"error", err)
			}
			continue
		}

		units = append(units, *unit)
	}

	j.ChaptersToPolish = len(units)
	return units, nil
}

// createPolishWorkUnit creates a single LLM work unit for polishing a chapter.
func (j *Job) createPolishWorkUnit(ctx context.Context, chapter *ChapterState) (*jobs.WorkUnit, error) {
	// Get system prompt (with possible book-level override)
	systemPrompt := j.Book.GetPrompt(PromptKeyPolishSystem)
	if systemPrompt == "" {
		systemPrompt = PolishSystemPrompt
	}

	// Build user prompt
	userPrompt := BuildPolishPrompt(chapter.Title, chapter.MechanicalText)

	// Create JSON schema for structured output
	schemaBytes, err := json.Marshal(PolishJSONSchema())
	if err != nil {
		return nil, fmt.Errorf("failed to marshal JSON schema: %w", err)
	}

	responseFormat := &providers.ResponseFormat{
		Type:       "json_schema",
		JSONSchema: schemaBytes,
	}

	request := &providers.ChatRequest{
		Model: "", // Will be set by scheduler
		Messages: []providers.Message{
			{Role: "system", Content: systemPrompt},
			{Role: "user", Content: userPrompt},
		},
		ResponseFormat: responseFormat,
		MaxTokens:      2000, // Limit response size for edits
	}

	// Create work unit
	unitID := uuid.New().String()
	unit := &jobs.WorkUnit{
		ID:          unitID,
		Type:        jobs.WorkUnitTypeLLM,
		Provider:    j.Book.TocProvider, // Reuse ToC provider
		JobID:       j.RecordID,
		ChatRequest: request,
		Metrics: &jobs.WorkUnitMetrics{
			Stage:     "structure-polish",
			ItemKey:   fmt.Sprintf("polish_%s", chapter.EntryID),
			PromptKey: PromptKeyPolishSystem,
			PromptCID: j.Book.GetPromptCID(PromptKeyPolishSystem),
			BookID:    j.Book.BookID,
		},
	}

	// Register work unit
	j.Tracker.Register(unitID, WorkUnitInfo{
		UnitType:  WorkUnitTypePolish,
		Phase:     PhasePolish,
		ChapterID: chapter.EntryID,
	})

	return unit, nil
}

// ProcessPolishResult parses and applies polish results for a chapter.
func (j *Job) ProcessPolishResult(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) error {
	logger := svcctx.LoggerFrom(ctx)

	chapter := j.GetChapterByEntryID(info.ChapterID)
	if chapter == nil {
		return fmt.Errorf("chapter not found: %s", info.ChapterID)
	}

	if !result.Success || result.ChatResult == nil {
		// Mark as failed but continue
		j.PolishFailed++
		chapter.PolishedText = chapter.MechanicalText // Fallback to mechanical
		chapter.PolishDone = true
		return result.Error
	}

	// Parse JSON response
	var content []byte
	if len(result.ChatResult.ParsedJSON) > 0 {
		content = result.ChatResult.ParsedJSON
	} else if result.ChatResult.Content != "" {
		content = []byte(result.ChatResult.Content)
	} else {
		// No response, use mechanical text
		chapter.PolishedText = chapter.MechanicalText
		chapter.PolishDone = true
		j.ChaptersPolished++
		return nil
	}

	var polishResult PolishResult
	if err := json.Unmarshal(content, &polishResult); err != nil {
		if logger != nil {
			logger.Warn("failed to parse polish result, using mechanical text",
				"chapter", chapter.EntryID,
				"error", err)
		}
		chapter.PolishedText = chapter.MechanicalText
		chapter.PolishDone = true
		j.ChaptersPolished++
		return nil
	}

	// Apply edits
	polishedText := ApplyEdits(chapter.MechanicalText, polishResult.Edits)

	// Update chapter
	chapter.EditsApplied = polishResult.Edits
	chapter.PolishedText = polishedText
	chapter.WordCount = len(strings.Fields(polishedText))
	chapter.PolishDone = true

	// Update paragraphs with polished text
	// Re-split polished text into paragraphs
	chapter.Paragraphs = SplitIntoParagraphs(polishedText, chapter.StartPage)
	for _, para := range chapter.Paragraphs {
		para.PolishedText = para.RawText // For now, paragraph text is same as raw
	}

	if logger != nil {
		logger.Debug("polished chapter text",
			"chapter", chapter.EntryID,
			"edits", len(polishResult.Edits),
			"words", chapter.WordCount)
	}

	j.ChaptersPolished++
	return nil
}

// PersistPolishResults persists polish results to DefraDB.
func (j *Job) PersistPolishResults(ctx context.Context) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	for _, chapter := range j.Chapters {
		if !chapter.PolishDone || chapter.DocID == "" {
			continue
		}

		// Convert edits to JSON for storage
		var editsJSON []byte
		if len(chapter.EditsApplied) > 0 {
			var err error
			editsJSON, err = json.Marshal(chapter.EditsApplied)
			if err != nil {
				editsJSON = []byte("[]")
			}
		} else {
			editsJSON = []byte("[]")
		}

		// Update chapter with polished text and edits
		sink.Send(defra.WriteOp{
			Collection: "Chapter",
			DocID:      chapter.DocID,
			Document: map[string]any{
				"polished_text":      chapter.PolishedText,
				"word_count":         chapter.WordCount,
				"polish_complete":    true,
				"edits_applied_json": string(editsJSON),
			},
			Op: defra.OpUpdate,
		})
	}

	return nil
}

// AllPolishDone returns true if all chapters have been polished.
func (j *Job) AllPolishDone() bool {
	for _, ch := range j.Chapters {
		if !ch.PolishDone {
			return false
		}
	}
	return true
}
