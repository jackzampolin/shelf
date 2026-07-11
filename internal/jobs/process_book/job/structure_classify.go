package job

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"sync"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// Keep the prompt, four keyed result maps, and bounded completion comfortably
// inside a 65K context even for books with hundreds of fine-grained entries.
const structureClassifyChunkSize = 64

// transitionToStructureClassify starts the classify phase.
func (j *Job) transitionToStructureClassify(ctx context.Context) []jobs.WorkUnit {
	j.Book.SetStructurePhase(StructPhaseClassify)
	logger := svcctx.LoggerFrom(ctx)
	// Persist phase (async - memory is authoritative during execution)
	common.PersistStructurePhaseAsync(ctx, j.Book)

	if logger != nil {
		logger.Debug("transitioning to classify phase",
			"book_id", j.Book.BookID)
	}

	chapters := j.Book.GetStructureChapters()
	var units []jobs.WorkUnit
	for start := 0; start < len(chapters); start += structureClassifyChunkSize {
		end := start + structureClassifyChunkSize
		if end > len(chapters) {
			end = len(chapters)
		}
		unit, err := j.createStructureClassifyChunkWorkUnit(ctx, chapters[start:end], start, end, 0)
		if err != nil {
			j.noWorkFailure = fmt.Sprintf("failed to create structure classification chunk %d-%d: %v", start, end, err)
			if logger != nil {
				logger.Error("failed to create classify work unit", "start", start, "end", end, "error", err)
			}
			return nil
		}
		units = append(units, *unit)
	}
	if len(units) == 0 {
		j.noWorkFailure = "structure classification has no chapters"
		return nil
	}
	j.Book.SetStructureClassifyPending(true)
	return units
}

// createStructureClassifyWorkUnit creates an LLM work unit for matter classification.
func (j *Job) createStructureClassifyWorkUnit(ctx context.Context) (*jobs.WorkUnit, error) {
	chapters := j.Book.GetStructureChapters()
	return j.createStructureClassifyChunkWorkUnit(ctx, chapters, 0, len(chapters), 0)
}

func (j *Job) createStructureClassifyChunkWorkUnit(ctx context.Context, chapters []*common.ChapterState, start, end, retryCount int) (*jobs.WorkUnit, error) {
	systemPrompt := j.GetPrompt(common.PromptKeyClassifySystem)
	if systemPrompt == "" {
		systemPrompt = common.ClassifySystemPrompt
	}

	userPrompt := common.BuildClassifyPrompt(chapters, j.Book.TotalPages)

	// Inner json_schema object only; vLLM requires response_format.json_schema.name.
	schemaBytes, err := json.Marshal(common.ClassifyJSONSchema())
	if err != nil {
		return nil, fmt.Errorf("failed to marshal JSON schema: %w", err)
	}

	responseFormat := &providers.ResponseFormat{
		Type:       "json_schema",
		JSONSchema: schemaBytes,
	}

	request := &providers.ChatRequest{
		Model:     "",
		MaxTokens: common.ClassifyMaxOutputTokens(len(chapters)),
		Messages: []providers.Message{
			{Role: "system", Content: systemPrompt},
			{Role: "user", Content: userPrompt},
		},
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
			Stage:     "structure-classify",
			ItemKey:   fmt.Sprintf("classify_matter_%03d_%03d", start, end),
			PromptKey: common.PromptKeyClassifySystem,
			PromptCID: j.Book.GetPromptCID(common.PromptKeyClassifySystem),
			BookID:    j.Book.BookID,
		},
	}

	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:       WorkUnitTypeStructureClassify,
		StructurePhase: StructPhaseClassify,
		RetryCount:     retryCount,
		ClassifyStart:  start,
		ClassifyEnd:    end,
	})
	return unit, nil
}

// HandleStructureClassifyComplete processes classification result.
func (j *Job) HandleStructureClassifyComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	j.RemoveWorkUnit(result.WorkUnitID)
	logger := svcctx.LoggerFrom(ctx)
	chapters := j.Book.GetStructureChapters()
	if info.ClassifyStart < 0 || info.ClassifyEnd > len(chapters) || info.ClassifyStart >= info.ClassifyEnd {
		return nil, fmt.Errorf("invalid structure classification chunk %d-%d", info.ClassifyStart, info.ClassifyEnd)
	}
	chunk := chapters[info.ClassifyStart:info.ClassifyEnd]

	if !result.Success {
		return j.retryStructureClassifyChunk(ctx, info, chunk, result.Error)
	}

	// Parse and validate complete per-entry coverage before mutating the merged
	// classification. A schema-valid object may still omit arbitrary map keys.
	if err := j.processStructureClassifyResult(ctx, result, chunk); err != nil {
		if logger != nil {
			logger.Warn("invalid classification chunk result, retrying",
				"start", info.ClassifyStart,
				"end", info.ClassifyEnd,
				"retry_count", info.RetryCount,
				"error", err)
		}
		return j.retryStructureClassifyChunk(ctx, info, chunk, err)
	}

	if j.PendingWorkUnits() > 0 {
		return nil, nil
	}
	j.Book.SetStructureClassifyPending(false)
	// Persist the complete merged classification only after all chunks land.
	if err := j.persistClassifyResults(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to persist classification results", "error", err)
		}
		return nil, fmt.Errorf("failed to persist classification results: %w", err)
	}

	return j.transitionToStructurePolish(ctx), nil
}

func (j *Job) retryStructureClassifyChunk(ctx context.Context, info WorkUnitInfo, chunk []*common.ChapterState, cause error) ([]jobs.WorkUnit, error) {
	logger := svcctx.LoggerFrom(ctx)
	if info.RetryCount < MaxStructureRetries {
		unit, err := j.createStructureClassifyChunkWorkUnit(ctx, chunk, info.ClassifyStart, info.ClassifyEnd, info.RetryCount+1)
		if err != nil {
			return nil, fmt.Errorf("recreate structure classification chunk %d-%d: %w", info.ClassifyStart, info.ClassifyEnd, err)
		}
		if logger != nil {
			logger.Warn("classification chunk failed, retrying",
				"start", info.ClassifyStart,
				"end", info.ClassifyEnd,
				"retry_count", info.RetryCount+1,
				"max_retries", MaxStructureRetries,
				"error", cause)
		}
		return []jobs.WorkUnit{*unit}, nil
	}
	if logger != nil {
		logger.Error("classification chunk permanently failed",
			"start", info.ClassifyStart, "end", info.ClassifyEnd, "error", cause)
	}
	return nil, fmt.Errorf("structure classification chunk %d-%d failed after %d attempts: %w", info.ClassifyStart, info.ClassifyEnd, info.RetryCount+1, cause)
}

// processStructureClassifyResult parses and applies classification results.
func (j *Job) processStructureClassifyResult(ctx context.Context, result jobs.WorkResult, expected []*common.ChapterState) error {
	logger := svcctx.LoggerFrom(ctx)

	if result.ChatResult == nil {
		return fmt.Errorf("no chat result")
	}

	var content []byte
	if len(result.ChatResult.ParsedJSON) > 0 {
		content = result.ChatResult.ParsedJSON
	} else if result.ChatResult.Content != "" {
		content = []byte(result.ChatResult.Content)
	} else {
		return fmt.Errorf("empty response")
	}

	var classifyResult common.ClassifyResult
	if err := json.Unmarshal(content, &classifyResult); err != nil {
		return fmt.Errorf("failed to parse classification result: %w", err)
	}
	if err := validateStructureClassifyCoverage(classifyResult, expected); err != nil {
		return err
	}

	j.Book.ApplyStructureClassifyResult(classifyResult)

	if logger != nil {
		logger.Debug("applied matter classifications",
			"book_id", j.Book.BookID,
			"classifications", len(classifyResult.Classifications))
	}
	return nil
}

func validateStructureClassifyCoverage(result common.ClassifyResult, expected []*common.ChapterState) error {
	want := make(map[string]struct{}, len(expected))
	for _, chapter := range expected {
		if chapter == nil || chapter.EntryID == "" {
			return fmt.Errorf("classification chunk contains chapter without entry_id")
		}
		if _, duplicate := want[chapter.EntryID]; duplicate {
			return fmt.Errorf("classification chunk contains duplicate entry_id %s", chapter.EntryID)
		}
		want[chapter.EntryID] = struct{}{}
	}

	problems := make([]string, 0)
	check := func(name string, keys []string) {
		got := make(map[string]struct{}, len(keys))
		for _, key := range keys {
			got[key] = struct{}{}
		}
		var missing, extra []string
		for key := range want {
			if _, ok := got[key]; !ok {
				missing = append(missing, key)
			}
		}
		for key := range got {
			if _, ok := want[key]; !ok {
				extra = append(extra, key)
			}
		}
		sort.Strings(missing)
		sort.Strings(extra)
		if len(missing) > 0 {
			problems = append(problems, fmt.Sprintf("%s missing %s", name, strings.Join(missing, ",")))
		}
		if len(extra) > 0 {
			problems = append(problems, fmt.Sprintf("%s unexpected %s", name, strings.Join(extra, ",")))
		}
	}
	stringKeys := func(values map[string]string) []string {
		keys := make([]string, 0, len(values))
		for key := range values {
			keys = append(keys, key)
		}
		return keys
	}
	boolKeys := func(values map[string]bool) []string {
		keys := make([]string, 0, len(values))
		for key := range values {
			keys = append(keys, key)
		}
		return keys
	}
	check("classifications", stringKeys(result.Classifications))
	check("content_types", stringKeys(result.ContentTypes))
	check("audio_include", boolKeys(result.AudioInclude))
	check("reasoning", stringKeys(result.Reasoning))
	if len(problems) > 0 {
		return fmt.Errorf("incomplete structure classification: %s", strings.Join(problems, "; "))
	}
	return nil
}

// persistClassifyResults persists classification results to DefraDB with parallel direct writes.
// Classification results can be re-run on crash recovery.
func (j *Job) persistClassifyResults(ctx context.Context) error {
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
		if chapter.DocID == "" {
			continue
		}

		wg.Add(1)
		go func(ch *common.ChapterState) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			doc := map[string]any{
				"matter_type":   ch.MatterType,
				"content_type":  ch.ContentType,
				"audio_include": ch.AudioInclude,
			}
			if ch.ClassifyReasoning != "" {
				doc["classification_reasoning"] = ch.ClassifyReasoning
			}
			if ch.AudioIncludeReasoning != "" {
				doc["audio_include_reasoning"] = ch.AudioIncludeReasoning
			}

			result, err := defraStructureWriteWithRetry(ctx, func() (defra.WriteResult, error) {
				return defraClient.UpdateWithVersion(ctx, "Chapter", ch.DocID, doc)
			})
			if err != nil {
				mu.Lock()
				if firstErr == nil {
					firstErr = err
				}
				mu.Unlock()
				if logger != nil {
					logger.Warn("failed to persist chapter classify result",
						"chapter_id", ch.EntryID,
						"doc_id", ch.DocID,
						"error", err)
				}
				return
			}
			j.Book.TrackWrite("Chapter", ch.DocID, result.CID)
			mu.Lock()
			count++
			mu.Unlock()
		}(chapter)
	}
	wg.Wait()

	if logger != nil {
		logger.Debug("persisted classify results", "count", count)
	}
	return firstErr
}
