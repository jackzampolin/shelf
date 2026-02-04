package job

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"sync"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// MaxStructureRetries is the maximum number of retries for structure operations.
const MaxStructureRetries = 3

// Structure phase constants (aligned with common_structure)
const (
	StructPhaseBuild    = "build"
	StructPhaseExtract  = "extract"
	StructPhaseClassify = "classify"
	StructPhasePolish   = "polish"
	StructPhaseFinalize = "finalize"
)

// maxPersistConcurrency bounds parallel DB writes in persist functions.
const maxPersistConcurrency = 5

// StartStructurePhase initializes and starts the structure phase.
func (j *Job) StartStructurePhase(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Mark structure as started
	if err := j.Book.StructureStart(); err != nil {
		if logger != nil {
			logger.Debug("structure already started", "error", err)
		}
		return nil
	}
	// Use async persist: memory is already updated by StructureStart(),
	// fire-and-forget DB write removes latency from critical path
	j.Book.PersistOpStateAsync(ctx, common.OpStructure)

	// Load linked entries (uses cache, refreshed after finalize_toc)
	entries, err := common.RefreshLinkedEntries(ctx, j.Book, j.TocDocID)
	if err != nil {
		if logger != nil {
			logger.Error("failed to load linked entries for structure",
				"book_id", j.Book.BookID,
				"error", err)
		}
		j.Book.StructureFail(MaxBookOpRetries)
		j.Book.PersistOpStateAsync(ctx, common.OpStructure)
		return nil
	}

	// Initialize structure state on BookState
	j.Book.SetStructureChapters(make([]*common.ChapterState, 0))
	j.Book.SetStructureClassifications(make(map[string]string))
	j.Book.SetStructureClassifyReasonings(make(map[string]string))

	if logger != nil {
		logger.Info("starting structure phase",
			"book_id", j.Book.BookID,
			"linked_entries", len(entries))
	}

	// Phase 1: Build skeleton (synchronous)
	j.Book.SetStructurePhase(StructPhaseBuild)
	if err := j.buildChapterSkeleton(ctx, entries); err != nil {
		if logger != nil {
			logger.Error("failed to build skeleton", "error", err)
		}
		j.Book.StructureFail(MaxBookOpRetries)
		j.Book.PersistOpStateAsync(ctx, common.OpStructure)
		return nil
	}

	// Update progress (async - memory is updated by SetStructureProgress)
	chapters := j.Book.GetStructureChapters()
	j.Book.SetStructureProgress(len(chapters), 0, 0, 0)
	j.Book.PersistStructurePhaseAsync(ctx)

	// Phase 2: Extract text (synchronous)
	j.Book.SetStructurePhase(StructPhaseExtract)
	chaptersExtracted := j.extractAllChapters(ctx)

	// Update progress
	j.Book.SetStructureProgress(len(chapters), chaptersExtracted, 0, 0)
	if err := common.PersistStructurePhase(ctx, j.Book); err != nil {
		if logger != nil {
			logger.Error("failed to persist structure phase, crash recovery may resume from wrong state",
				"phase", StructPhaseExtract,
				"book_id", j.Book.BookID,
				"error", err)
		}
	}

	// Persist extract results
	if err := j.persistExtractResults(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to persist extract results", "error", err)
		}
	}

	// Phase 3: Classify (LLM work unit)
	return j.transitionToStructureClassify(ctx)
}

// buildChapterSkeleton builds the chapter skeleton from linked ToC entries.
func (j *Job) buildChapterSkeleton(ctx context.Context, entries []*common.LinkedTocEntry) error {
	logger := svcctx.LoggerFrom(ctx)

	// Filter to entries with actual pages
	var linkedEntries []*common.LinkedTocEntry
	for _, entry := range entries {
		if entry.ActualPage != nil {
			linkedEntries = append(linkedEntries, entry)
		}
	}

	if len(linkedEntries) == 0 {
		return fmt.Errorf("no linked ToC entries found")
	}

	// Sort by sort_order
	sort.Slice(linkedEntries, func(i, k int) bool {
		return linkedEntries[i].SortOrder < linkedEntries[k].SortOrder
	})

	// Create chapters with boundaries
	chapters := make([]*common.ChapterState, 0, len(linkedEntries))
	for i, entry := range linkedEntries {
		chapter := &common.ChapterState{
			EntryID:     fmt.Sprintf("ch_%03d", i+1),
			Title:       entry.Title,
			Level:       entry.Level,
			LevelName:   entry.LevelName,
			EntryNumber: entry.EntryNumber,
			SortOrder:   entry.SortOrder,
			Source:      "toc",
			TocEntryID:  entry.DocID,
			StartPage:   *entry.ActualPage,
			MatterType:  "body", // Default, updated in classify phase
		}

		// Calculate end page
		if i < len(linkedEntries)-1 {
			nextEntry := linkedEntries[i+1]
			if nextEntry.ActualPage != nil {
				chapter.EndPage = *nextEntry.ActualPage - 1
			}
		} else {
			chapter.EndPage = j.Book.TotalPages
		}

		// Ensure end_page >= start_page
		if chapter.EndPage < chapter.StartPage {
			chapter.EndPage = chapter.StartPage
		}

		chapters = append(chapters, chapter)
	}

	// Store chapters on BookState
	j.Book.SetStructureChapters(chapters)

	// Build hierarchy (set parent_id based on levels)
	j.buildChapterHierarchy()

	if logger != nil {
		logger.Info("built chapter skeleton",
			"book_id", j.Book.BookID,
			"chapters", len(chapters))
	}

	// Persist skeleton to DefraDB
	return j.persistChapterSkeleton(ctx)
}

// buildChapterHierarchy sets parent_id values based on chapter levels.
func (j *Job) buildChapterHierarchy() {
	recentByLevel := make(map[int]*common.ChapterState)
	chapters := j.Book.GetStructureChapters()

	for _, chapter := range chapters {
		if chapter.Level > 1 {
			if parent, ok := recentByLevel[chapter.Level-1]; ok {
				chapter.ParentID = parent.EntryID
				j.Book.UpdateChapter(chapter) // Save changes back
			}
		}
		recentByLevel[chapter.Level] = chapter
		for lvl := chapter.Level + 1; lvl <= 5; lvl++ {
			delete(recentByLevel, lvl)
		}
	}
}

// persistChapterSkeleton saves the chapter skeleton to DefraDB using upsert.
// This preserves DocIDs/CIDs across re-runs, enabling change history tracking.
func (j *Job) persistChapterSkeleton(ctx context.Context) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}
	logger := svcctx.LoggerFrom(ctx)

	// Mark structure as started on Book
	if _, err := common.SendTracked(ctx, j.Book, defra.WriteOp{
		Collection: "Book",
		DocID:      j.Book.BookID,
		Document: map[string]any{
			"structure_started": true,
		},
		Op: defra.OpUpdate,
	}); err != nil && logger != nil {
		logger.Warn("failed to persist structure start", "book_id", j.Book.BookID, "error", err)
	}

	chapters := j.Book.GetStructureChapters()

	// Pre-compute unique keys (must happen before concurrent access)
	for _, chapter := range chapters {
		chapter.UniqueKey = j.generateChapterUniqueKey(chapter)
	}

	// Upsert chapters concurrently with bounded parallelism
	var wg sync.WaitGroup
	sem := make(chan struct{}, maxPersistConcurrency)
	var mu sync.Mutex
	var firstErr error

	for _, chapter := range chapters {
		wg.Add(1)
		go func(ch *common.ChapterState) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			doc := map[string]any{
				"book_id":      j.Book.BookID,
				"unique_key":   ch.UniqueKey,
				"entry_id":     ch.EntryID,
				"title":        ch.Title,
				"level":        ch.Level,
				"level_name":   ch.LevelName,
				"entry_number": ch.EntryNumber,
				"sort_order":   ch.SortOrder,
				"start_page":   ch.StartPage,
				"end_page":     ch.EndPage,
				"matter_type":  ch.MatterType,
				"parent_id":    ch.ParentID,
				"source":       ch.Source,
			}

			if ch.TocEntryID != "" {
				doc["toc_entry_id"] = ch.TocEntryID
			}

			filter := map[string]any{
				"unique_key": map[string]any{"_eq": ch.UniqueKey},
			}

			result, err := defraClient.UpsertWithVersion(ctx, "Chapter", filter, doc, doc)
			if err != nil {
				mu.Lock()
				if firstErr == nil {
					firstErr = fmt.Errorf("failed to upsert chapter %s: %w", ch.EntryID, err)
				}
				mu.Unlock()
				return
			}
			docID := result.DocID
			if docID == "" {
				docID = ch.DocID
			}
			ch.DocID = docID
			ch.CID = result.CID
			j.Book.UpdateChapter(ch)
			j.Book.TrackWrite("Chapter", docID, result.CID)

			if logger != nil {
				logger.Debug("upserted chapter", "entry_id", ch.EntryID, "unique_key", ch.UniqueKey, "doc_id", docID)
			}
		}(chapter)
	}
	wg.Wait()

	return firstErr
}

// generateChapterUniqueKey creates a stable unique_key for upsert.
// Format: "{book_id}:{toc_entry_id}" for ToC-linked chapters,
// or "{book_id}:orphan:{sort_order}" for chapters without ToC entries.
func (j *Job) generateChapterUniqueKey(chapter *common.ChapterState) string {
	if chapter.TocEntryID != "" {
		return fmt.Sprintf("%s:%s", j.Book.BookID, chapter.TocEntryID)
	}
	// Orphan chapters (not from ToC) use sort_order for stability
	return fmt.Sprintf("%s:orphan:%d", j.Book.BookID, chapter.SortOrder)
}

// extractAllChapters extracts text for all chapters. Returns count of chapters extracted.
func (j *Job) extractAllChapters(ctx context.Context) int {
	logger := svcctx.LoggerFrom(ctx)
	chapters := j.Book.GetStructureChapters()
	chaptersExtracted := 0

	for _, chapter := range chapters {
		// Extract text from pages in range
		pageTexts := j.extractChapterPages(chapter.StartPage, chapter.EndPage)

		// Merge and clean text
		chapter.MechanicalText = common.MergeChapterPages(pageTexts)
		chapter.WordCount = common.CountWords(chapter.MechanicalText)
		chapter.ExtractDone = true
		j.Book.UpdateChapter(chapter) // Save changes back

		chaptersExtracted++
	}

	if logger != nil {
		logger.Info("extracted chapter text",
			"book_id", j.Book.BookID,
			"chapters_extracted", chaptersExtracted)
	}

	return chaptersExtracted
}

// extractChapterPages extracts text from a range of pages.
func (j *Job) extractChapterPages(startPage, endPage int) []common.PageText {
	var pageTexts []common.PageText

	for pageNum := startPage; pageNum <= endPage; pageNum++ {
		pageState := j.Book.GetPage(pageNum)
		if pageState == nil {
			continue
		}

		// Get OCR markdown text
		ocrText := pageState.GetOcrMarkdown()
		if ocrText == "" {
			continue
		}

		header := pageState.GetHeader()
		footer := pageState.GetFooter()
		stripped := common.StripHeaderFooter(ocrText, header, footer)

		pageTexts = append(pageTexts, common.PageText{
			ScanPage:    pageNum,
			RawText:     ocrText,
			CleanedText: common.CleanPageText(stripped),
		})
	}

	return pageTexts
}

// persistExtractResults saves extract results to DefraDB with parallel direct writes.
// Extract results can be recalculated on crash recovery from page OCR data.
func (j *Job) persistExtractResults(ctx context.Context) error {
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
		if chapter.DocID == "" || !chapter.ExtractDone {
			continue
		}

		wg.Add(1)
		go func(ch *common.ChapterState) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			result, err := defraClient.UpdateWithVersion(ctx, "Chapter", ch.DocID, map[string]any{
				"mechanical_text":  ch.MechanicalText,
				"word_count":       ch.WordCount,
				"extract_complete": true,
			})
			if err != nil {
				mu.Lock()
				if firstErr == nil {
					firstErr = err
				}
				mu.Unlock()
				if logger != nil {
					logger.Warn("failed to persist chapter extract result",
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
		logger.Debug("persisted extract results", "count", count)
	}
	return firstErr
}

// transitionToStructureClassify starts the classify phase.
func (j *Job) transitionToStructureClassify(ctx context.Context) []jobs.WorkUnit {
	j.Book.SetStructurePhase(StructPhaseClassify)
	logger := svcctx.LoggerFrom(ctx)
	if err := common.PersistStructurePhase(ctx, j.Book); err != nil {
		if logger != nil {
			logger.Error("failed to persist structure phase, crash recovery may resume from wrong state",
				"phase", StructPhaseClassify,
				"book_id", j.Book.BookID,
				"error", err)
		}
	}

	if logger != nil {
		logger.Info("transitioning to classify phase",
			"book_id", j.Book.BookID)
	}

	unit, err := j.createStructureClassifyWorkUnit(ctx)
	if err != nil {
		if logger != nil {
			logger.Warn("failed to create classify work unit, skipping to polish", "error", err)
		}
		return j.transitionToStructurePolish(ctx)
	}

	return []jobs.WorkUnit{*unit}
}

// createStructureClassifyWorkUnit creates an LLM work unit for matter classification.
func (j *Job) createStructureClassifyWorkUnit(ctx context.Context) (*jobs.WorkUnit, error) {
	systemPrompt := j.GetPrompt(common.PromptKeyClassifySystem)
	if systemPrompt == "" {
		systemPrompt = common.ClassifySystemPrompt
	}

	chapters := j.Book.GetStructureChapters()
	userPrompt := common.BuildClassifyPrompt(chapters, j.Book.TotalPages)

	schemaBytes, err := json.Marshal(common.ClassifyJSONSchema())
	if err != nil {
		return nil, fmt.Errorf("failed to marshal JSON schema: %w", err)
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
			ItemKey:   "classify_matter",
			PromptKey: common.PromptKeyClassifySystem,
			PromptCID: j.Book.GetPromptCID(common.PromptKeyClassifySystem),
			BookID:    j.Book.BookID,
		},
	}

	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:       WorkUnitTypeStructureClassify,
		StructurePhase: StructPhaseClassify,
	})

	j.Book.SetStructureClassifyPending(true)
	return unit, nil
}

// HandleStructureClassifyComplete processes classification result.
func (j *Job) HandleStructureClassifyComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	j.RemoveWorkUnit(result.WorkUnitID)
	logger := svcctx.LoggerFrom(ctx)

	if !result.Success {
		if info.RetryCount < MaxStructureRetries {
			if logger != nil {
				logger.Warn("classification failed, retrying",
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			unit, err := j.createStructureClassifyWorkUnit(ctx)
			if err != nil {
				return j.transitionToStructurePolish(ctx), nil
			}
			j.Tracker.Register(unit.ID, WorkUnitInfo{
				UnitType:       WorkUnitTypeStructureClassify,
				StructurePhase: StructPhaseClassify,
				RetryCount:     info.RetryCount + 1,
			})
			return []jobs.WorkUnit{*unit}, nil
		}
		if logger != nil {
			logger.Warn("classification permanently failed, skipping to polish")
		}
		return j.transitionToStructurePolish(ctx), nil
	}

	// Process classification result
	if err := j.processStructureClassifyResult(ctx, result); err != nil {
		if logger != nil {
			logger.Warn("failed to process classification result", "error", err)
		}
	}

	// Persist classification results
	if err := j.persistClassifyResults(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to persist classification results", "error", err)
		}
	}

	return j.transitionToStructurePolish(ctx), nil
}

// processStructureClassifyResult parses and applies classification results.
func (j *Job) processStructureClassifyResult(ctx context.Context, result jobs.WorkResult) error {
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

	// Store classifications on BookState
	j.Book.SetStructureClassifications(classifyResult.Classifications)
	if classifyResult.Reasoning != nil {
		j.Book.SetStructureClassifyReasonings(classifyResult.Reasoning)
	}

	// Apply to chapters
	chapters := j.Book.GetStructureChapters()
	classifications := j.Book.GetStructureClassifications()
	reasonings := j.Book.GetStructureClassifyReasonings()
	for _, chapter := range chapters {
		modified := false
		if matterType, ok := classifications[chapter.EntryID]; ok {
			chapter.MatterType = matterType
			modified = true
		}
		if contentType, ok := classifyResult.ContentTypes[chapter.EntryID]; ok {
			chapter.ContentType = contentType
			modified = true
		}
		if include, ok := classifyResult.AudioInclude[chapter.EntryID]; ok {
			chapter.AudioInclude = include
			modified = true
		}
		if reasoning, ok := reasonings[chapter.EntryID]; ok {
			chapter.ClassifyReasoning = reasoning
			chapter.AudioIncludeReasoning = reasoning
			modified = true
		}
		if modified {
			j.Book.UpdateChapter(chapter) // Save changes back
		}
	}

	if logger != nil {
		logger.Info("applied matter classifications",
			"book_id", j.Book.BookID,
			"classifications", len(classifications))
	}

	j.Book.SetStructureClassifyPending(false)
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

			result, err := defraClient.UpdateWithVersion(ctx, "Chapter", ch.DocID, doc)
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

// transitionToStructurePolish starts the polish phase.
func (j *Job) transitionToStructurePolish(ctx context.Context) []jobs.WorkUnit {
	j.Book.SetStructurePhase(StructPhasePolish)
	logger := svcctx.LoggerFrom(ctx)
	if err := common.PersistStructurePhase(ctx, j.Book); err != nil {
		if logger != nil {
			logger.Error("failed to persist structure phase, crash recovery may resume from wrong state",
				"phase", StructPhasePolish,
				"book_id", j.Book.BookID,
				"error", err)
		}
	}

	chapters := j.Book.GetStructureChapters()
	if logger != nil {
		logger.Info("transitioning to polish phase",
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
			chapter.PolishDone = true
			j.Book.UpdateChapter(chapter) // Save changes back
			j.Book.IncrementStructurePolished()
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

	// Process polish result
	if err := j.processStructurePolishResult(ctx, result, info); err != nil {
		if logger != nil {
			logger.Warn("failed to process polish result",
				"chapter", info.ChapterID,
				"error", err)
		}
	}

	j.RemoveWorkUnit(result.WorkUnitID)

	// Check if all polish done
	if j.allStructurePolishDone() {
		if err := j.persistPolishResults(ctx); err != nil {
			if logger != nil {
				logger.Warn("failed to persist polish results", "error", err)
			}
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
		j.Book.IncrementStructurePolishFailed()
		chapter.PolishDone = true
		chapter.PolishFailed = true
		chapter.PolishedText = chapter.MechanicalText // Fallback to mechanical text
		j.Book.UpdateChapter(chapter)                 // Save changes back
		if logger != nil {
			logger.Error("chapter polish failed, degraded quality - using mechanical text",
				"chapter_id", chapter.EntryID,
				"title", chapter.Title,
				"book_id", j.Book.BookID,
				"reason", reason,
				"error", err)
		}
		if err != nil {
			return fmt.Errorf("polish failed for chapter %s, %s: %v", chapter.EntryID, reason, err)
		}
		return fmt.Errorf("polish failed for chapter %s, %s", chapter.EntryID, reason)
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
	chapter.PolishedText = common.ApplyEdits(chapter.MechanicalText, polishResult.Edits)
	chapter.WordCount = common.CountWords(chapter.PolishedText)
	chapter.PolishDone = true
	j.Book.UpdateChapter(chapter) // Save changes back

	j.Book.IncrementStructurePolished()

	return nil
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

			result, err := defraClient.UpdateWithVersion(ctx, "Chapter", ch.DocID, map[string]any{
				"polished_text":   ch.PolishedText,
				"word_count":      ch.WordCount,
				"polish_complete": true,
				"polish_failed":   ch.PolishFailed,
			})
			if err != nil {
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
			j.Book.TrackWrite("Chapter", ch.DocID, result.CID)
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

// completeStructurePhase finalizes the structure job.
func (j *Job) completeStructurePhase(ctx context.Context) ([]jobs.WorkUnit, error) {
	logger := svcctx.LoggerFrom(ctx)

	j.Book.SetStructurePhase(StructPhaseFinalize)
	// Use sync write for phase transition to ensure crash recovery works correctly
	if err := common.PersistStructurePhase(ctx, j.Book); err != nil {
		if logger != nil {
			logger.Error("failed to persist structure phase",
				"phase", StructPhaseFinalize,
				"book_id", j.Book.BookID,
				"error", err)
		}
		// Continue with finalization despite phase persist failure - the data is more important
	}

	// Finalize - create paragraphs, update book status
	if err := j.finalizeStructure(ctx); err != nil {
		if logger != nil {
			logger.Error("failed to finalize structure", "error", err)
		}
		return nil, fmt.Errorf("finalization failed: %w", err)
	}

	j.Book.StructureComplete()
	// Use sync write for completion to ensure state is persisted before returning
	if _, err := common.PersistOpComplete(ctx, j.Book, common.OpStructure); err != nil {
		if logger != nil {
			logger.Error("failed to persist structure completion", "error", err)
		}
		// Roll back in-memory state to match database - completion wasn't persisted
		j.Book.StructureReset()
		j.Book.StructureStart()
		j.Book.SetStructurePhase(StructPhaseFinalize) // Keep phase to indicate we were in finalize
		return nil, fmt.Errorf("structure completed but failed to persist: %w", err)
	}

	chapters := j.Book.GetStructureChapters()
	_, _, polished, failed := j.Book.GetStructureProgress()
	if logger != nil {
		logger.Info("structure phase complete",
			"book_id", j.Book.BookID,
			"chapters", len(chapters),
			"polished", polished,
			"failed", failed)
	}

	return nil, nil
}

// finalizeStructure marks structure as complete.
// Polish results were already persisted via sync writes in persistPolishResults.
// The sync write here ensures completion is durable before returning.
func (j *Job) finalizeStructure(ctx context.Context) error {
	// Mark book structure as complete using sync write.
	// This ensures completion is durable before returning.
	_, err := common.SendTracked(ctx, j.Book, defra.WriteOp{
		Collection: "Book",
		DocID:      j.Book.BookID,
		Document: map[string]any{
			"structure_complete": true,
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return fmt.Errorf("failed to mark structure complete: %w", err)
	}

	return nil
}
