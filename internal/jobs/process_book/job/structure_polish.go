package job

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// transitionToStructurePolish starts the polish phase.
func (j *Job) transitionToStructurePolish(ctx context.Context) []jobs.WorkUnit {
	j.Book.SetStructurePhase(StructPhasePolish)
	logger := svcctx.LoggerFrom(ctx)
	// Persist phase (async - memory is authoritative during execution)
	common.PersistStructurePhaseAsync(ctx, j.Book)

	chapters := j.Book.GetStructureChapters()
	if logger != nil {
		logger.Debug("transitioning to polish phase",
			"book_id", j.Book.BookID,
			"chapters", len(chapters))
	}

	return j.createStructurePolishWorkUnits(ctx)
}

// createStructurePolishWorkUnits creates work units for all chapters needing polish.
func (j *Job) createStructurePolishWorkUnits(ctx context.Context) []jobs.WorkUnit {
	var units []jobs.WorkUnit
	chapters := j.Book.GetStructureChapters()

	for _, chapter := range chapters {
		if chapter.PolishDone || chapter.MechanicalText == "" {
			continue
		}
		if !chapter.AudioInclude {
			chapter.PolishedText = chapter.MechanicalText
			chapter.EditsAppliedJSON = "[]"
			chapter.PolishDone = true
			j.Book.UpdateChapter(chapter) // Save changes back
			j.incrementStructurePolished(ctx)
			if err := j.persistChapterPolishResult(ctx, chapter); err != nil {
				if logger := svcctx.LoggerFrom(ctx); logger != nil {
					logger.Warn("failed to persist skipped chapter polish result",
						"chapter_id", chapter.EntryID,
						"doc_id", chapter.DocID,
						"error", err)
				}
			}
			continue
		}

		unit := j.createChapterPolishWorkUnit(ctx, chapter)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units
}

// createChapterPolishWorkUnit creates a polish work unit for a chapter.
func (j *Job) createChapterPolishWorkUnit(ctx context.Context, chapter *common.ChapterState) *jobs.WorkUnit {
	systemPrompt := j.GetPrompt(common.PromptKeyPolishSystem)
	if systemPrompt == "" {
		systemPrompt = common.PolishSystemPrompt
	}

	userPrompt := common.BuildPolishPrompt(chapter)

	// Inner json_schema object only; vLLM requires response_format.json_schema.name.
	schemaBytes, err := json.Marshal(common.PolishJSONSchema())
	if err != nil {
		return nil
	}

	responseFormat := &providers.ResponseFormat{
		Type:       "json_schema",
		JSONSchema: schemaBytes,
	}

	request := &providers.ChatRequest{
		Model: "",
		Messages: []providers.Message{
			{Role: "system", Content: systemPrompt},
			{Role: "user", Content: userPrompt},
		},
		MaxTokens:      common.MaxPolishOutputTokens,
		ResponseFormat: responseFormat,
	}

	unitID := uuid.New().String()
	unit := &jobs.WorkUnit{
		ID:          unitID,
		Type:        jobs.WorkUnitTypeLLM,
		Provider:    j.Book.TocProvider,
		JobID:       j.RecordID,
		ChatRequest: request,
		Metrics: &jobs.WorkUnitMetrics{
			Stage:     "structure-polish",
			ItemKey:   fmt.Sprintf("polish_%s", chapter.EntryID),
			PromptKey: common.PromptKeyPolishSystem,
			PromptCID: j.Book.GetPromptCID(common.PromptKeyPolishSystem),
			BookID:    j.Book.BookID,
		},
	}

	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:       WorkUnitTypeStructurePolish,
		StructurePhase: StructPhasePolish,
		ChapterID:      chapter.EntryID,
	})

	return unit
}

// HandleStructurePolishComplete processes polish result for a chapter.
func (j *Job) HandleStructurePolishComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	logger := svcctx.LoggerFrom(ctx)
	if !result.Success && info.RetryCount < MaxStructureRetries {
		j.RemoveWorkUnit(result.WorkUnitID)
		chapter := j.Book.GetChapterByEntryID(info.ChapterID)
		if chapter != nil {
			if unit := j.createChapterPolishWorkUnit(ctx, chapter); unit != nil {
				j.Tracker.Register(unit.ID, WorkUnitInfo{
					UnitType:       WorkUnitTypeStructurePolish,
					StructurePhase: StructPhasePolish,
					ChapterID:      info.ChapterID,
					RetryCount:     info.RetryCount + 1,
				})
				if logger != nil {
					logger.Warn("chapter polish failed, retrying",
						"chapter_id", info.ChapterID,
						"retry_count", info.RetryCount+1,
						"max_retries", MaxStructureRetries,
						"error", result.Error)
				}
				return []jobs.WorkUnit{*unit}, nil
			}
		}
	}

	// Process polish result
	if err := j.processStructurePolishResult(ctx, result, info); err != nil {
		if logger != nil {
			logger.Warn("failed to process polish result",
				"chapter", info.ChapterID,
				"error", err)
		}
		return nil, err
	}

	j.RemoveWorkUnit(result.WorkUnitID)

	// Check if all polish done
	if j.allStructurePolishDone() {
		if err := j.persistPolishResults(ctx); err != nil {
			if logger != nil {
				logger.Warn("failed to persist polish results", "error", err)
			}
			return nil, fmt.Errorf("failed to persist polish results: %w", err)
		}
		return j.completeStructurePhase(ctx)
	}

	return nil, nil
}

// processStructurePolishResult parses and applies polish results.
func (j *Job) processStructurePolishResult(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) error {
	// Find chapter (returns a copy)
	chapter := j.Book.GetChapterByEntryID(info.ChapterID)
	if chapter == nil {
		return fmt.Errorf("chapter not found: %s", info.ChapterID)
	}

	logger := svcctx.LoggerFrom(ctx)

	// Helper to mark chapter as failed and save
	markFailed := func(reason string, err error) error {
		j.incrementStructurePolishFailed(ctx)
		chapter.PolishDone = true
		chapter.PolishFailed = true
		chapter.PolishedText = chapter.MechanicalText // Fallback to mechanical text
		chapter.EditsAppliedJSON = "[]"
		j.Book.UpdateChapter(chapter) // Save changes back
		if persistErr := j.persistChapterPolishResult(ctx, chapter); persistErr != nil {
			if logger != nil {
				logger.Warn("failed to persist failed chapter polish result",
					"chapter_id", chapter.EntryID,
					"doc_id", chapter.DocID,
					"error", persistErr)
			}
			return fmt.Errorf("failed to persist failed chapter polish result for %s: %w", chapter.EntryID, persistErr)
		}
		if logger != nil {
			logger.Error("chapter polish failed, degraded quality - using mechanical text",
				"chapter_id", chapter.EntryID,
				"title", chapter.Title,
				"book_id", j.Book.BookID,
				"reason", reason,
				"error", err)
		}
		return nil
	}

	if !result.Success {
		return markFailed("work unit failed", result.Error)
	}

	if result.ChatResult == nil {
		return markFailed("no chat result", nil)
	}

	var content []byte
	if len(result.ChatResult.ParsedJSON) > 0 {
		content = result.ChatResult.ParsedJSON
	} else if result.ChatResult.Content != "" {
		content = []byte(result.ChatResult.Content)
	} else {
		return markFailed("empty response", nil)
	}

	var polishResult common.PolishResult
	if err := json.Unmarshal(content, &polishResult); err != nil {
		return markFailed("parse error", err)
	}

	// Apply edits
	editsJSON, err := json.Marshal(polishResult.Edits)
	if err != nil {
		return markFailed("marshal edits", err)
	}
	chapter.PolishedText = common.ApplyEdits(chapter.MechanicalText, polishResult.Edits)
	chapter.WordCount = common.CountWords(chapter.PolishedText)
	chapter.EditsAppliedJSON = string(editsJSON)
	chapter.PolishDone = true
	j.Book.UpdateChapter(chapter) // Save changes back

	j.incrementStructurePolished(ctx)
	if err := j.persistChapterPolishResult(ctx, chapter); err != nil {
		if logger != nil {
			logger.Warn("failed to persist chapter polish result",
				"chapter_id", chapter.EntryID,
				"doc_id", chapter.DocID,
				"error", err)
		}
		return fmt.Errorf("failed to persist chapter polish result for %s: %w", chapter.EntryID, err)
	}

	return nil
}

// Keep the durable structure counters current while the fan-out is running.
// Job heartbeat/last-progress already records liveness, but operators also need
// the detailed status endpoint to show how much of a large polish wave is done.
func (j *Job) incrementStructurePolished(ctx context.Context) {
	j.Book.IncrementStructurePolished()
	common.PersistStructurePhaseAsync(ctx, j.Book)
}

func (j *Job) incrementStructurePolishFailed(ctx context.Context) {
	j.Book.IncrementStructurePolishFailed()
	common.PersistStructurePhaseAsync(ctx, j.Book)
}

// allStructurePolishDone checks if all polish work is complete.
func (j *Job) allStructurePolishDone() bool {
	chapters := j.Book.GetStructureChapters()
	for _, chapter := range chapters {
		if !chapter.PolishDone && chapter.MechanicalText != "" {
			return false
		}
	}
	return true
}

// persistPolishResults saves polish results to DefraDB with parallel direct writes.
// Polish results are the final output and should be persisted before completion.
func (j *Job) persistPolishResults(ctx context.Context) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}
	logger := svcctx.LoggerFrom(ctx)
	chapters := j.Book.GetStructureChapters()

	var wg sync.WaitGroup
	sem := make(chan struct{}, maxPersistConcurrency)
	var mu sync.Mutex
	var firstErr error
	var count int

	for _, chapter := range chapters {
		if chapter.DocID == "" || !chapter.PolishDone {
			continue
		}

		wg.Add(1)
		go func(ch *common.ChapterState) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			if err := j.persistChapterPolishResult(ctx, ch); err != nil {
				mu.Lock()
				if firstErr == nil {
					firstErr = err
				}
				mu.Unlock()
				if logger != nil {
					logger.Warn("failed to persist chapter polish result",
						"chapter_id", ch.EntryID,
						"doc_id", ch.DocID,
						"error", err)
				}
				return
			}
			mu.Lock()
			count++
			mu.Unlock()
		}(chapter)
	}
	wg.Wait()

	if logger != nil {
		logger.Debug("persisted polish results", "count", count)
	}
	return firstErr
}

func (j *Job) persistChapterPolishResult(ctx context.Context, ch *common.ChapterState) error {
	if ch == nil || ch.DocID == "" || !ch.PolishDone {
		return nil
	}
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}
	editsJSON := ch.EditsAppliedJSON
	if editsJSON == "" {
		editsJSON = "[]"
	}

	result, err := defraStructureWriteWithRetry(ctx, func() (defra.WriteResult, error) {
		return defraClient.UpdateWithVersion(ctx, "Chapter", ch.DocID, map[string]any{
			"polished_text":      ch.PolishedText,
			"word_count":         ch.WordCount,
			"edits_applied_json": editsJSON,
			"polish_complete":    true,
			"polish_failed":      ch.PolishFailed,
		})
	})
	if err != nil {
		return err
	}
	ch.CID = result.CID
	j.Book.TrackWrite("Chapter", ch.DocID, result.CID)
	return nil
}
