package job

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"
	pattern_analyzer "github.com/jackzampolin/shelf/internal/agents/pattern_analyzer"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
	"github.com/jackzampolin/shelf/internal/types"
)

// CreateFinalizePatternWorkUnit creates a work unit for pattern analysis.
func (j *Job) CreateFinalizePatternWorkUnit(ctx context.Context) (*jobs.WorkUnit, error) {
	// Load candidate headings from Page.headings
	candidates := j.loadCandidateHeadings()

	// Load chapter start pages from DefraDB
	chapterStartPages, err := j.loadChapterStartPages(ctx)
	if err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("proceeding without chapter start pages", "error", err)
		}
	}

	// Get linked entries for context
	entries, _ := common.GetOrLoadLinkedEntries(ctx, j.Book, j.TocDocID)

	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		detectedCount := 0
		if j.FinalizePagePatternCtx != nil {
			detectedCount = len(j.FinalizePagePatternCtx.ChapterPatterns)
		}
		logger.Debug("pattern analysis context loaded",
			"candidate_count", len(candidates),
			"detected_chapters", detectedCount,
			"chapter_start_pages", len(chapterStartPages),
			"body_start", j.Book.GetBodyStart(),
			"body_end", j.Book.GetBodyEnd(),
			"linked_entries", len(entries))
	}

	// Build prompts with enhanced context
	systemPrompt := j.GetPrompt(pattern_analyzer.PromptKey)
	userPrompt := pattern_analyzer.BuildUserPrompt(pattern_analyzer.UserPromptData{
		LinkedEntries:     j.convertEntriesForPattern(entries),
		Candidates:        j.convertCandidatesForPattern(candidates),
		DetectedChapters:  j.convertDetectedChapters(),
		ChapterStartPages: chapterStartPages,
		BodyStart:         j.Book.GetBodyStart(),
		BodyEnd:           j.Book.GetBodyEnd(),
		TotalPages:        j.Book.TotalPages,
	})

	// Create chat request with structured output. Use the INNER json_schema object
	// ({name, schema}); vLLM strictly requires response_format.json_schema.name,
	// whereas OpenRouter tolerated marshaling the outer {type, json_schema} wrapper.
	schemaBytes, err := json.Marshal(pattern_analyzer.JSONSchema()["json_schema"])
	if err != nil {
		return nil, fmt.Errorf("failed to marshal JSON schema: %w", err)
	}
	responseFormat := &providers.ResponseFormat{
		Type:       "json_schema",
		JSONSchema: schemaBytes,
	}

	request := &providers.ChatRequest{
		Model:     "",
		MaxTokens: pattern_analyzer.MaxOutputTokens(len(entries)),
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
		Provider:    j.Book.TocProvider,
		JobID:       j.RecordID,
		ChatRequest: request,
		Metrics: &jobs.WorkUnitMetrics{
			Stage:     "toc-pattern",
			ItemKey:   "pattern_analysis",
			PromptKey: pattern_analyzer.PromptKey,
			PromptCID: j.GetPromptCID(pattern_analyzer.PromptKey),
			BookID:    j.Book.BookID,
		},
	}

	// Register work unit
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:      WorkUnitTypeFinalizePattern,
		FinalizePhase: FinalizePhasePattern,
	})

	return unit, nil
}

// HandleFinalizePatternComplete processes pattern analysis completion.
func (j *Job) HandleFinalizePatternComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	j.RemoveWorkUnit(result.WorkUnitID)
	logger := svcctx.LoggerFrom(ctx)

	if !result.Success {
		if info.RetryCount < MaxFinalizeRetries {
			if logger != nil {
				logger.Warn("pattern analysis failed, retrying",
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			unit, err := j.CreateFinalizePatternWorkUnit(ctx)
			if err != nil || unit == nil {
				return j.transitionToFinalizeDiscover(ctx), nil
			}
			j.Tracker.Register(unit.ID, WorkUnitInfo{
				UnitType:      WorkUnitTypeFinalizePattern,
				FinalizePhase: FinalizePhasePattern,
				RetryCount:    info.RetryCount + 1,
			})
			return []jobs.WorkUnit{*unit}, nil
		}
		if logger != nil {
			logger.Warn("pattern analysis permanently failed, skipping to discover",
				"book_id", j.Book.BookID,
				"retry_count", info.RetryCount,
				"error", result.Error)
		}
		// Mark pattern phase as skipped to prevent re-attempts on restart (async - memory is authoritative)
		j.Book.SetFinalizePhase(FinalizePhaseDiscover)
		common.PersistFinalizePhaseAsync(ctx, j.Book, FinalizePhaseDiscover)
		return j.transitionToFinalizeDiscover(ctx), nil
	}

	// Process pattern analysis result
	writeResult, err := j.processFinalizePatternResult(ctx, result)
	if err != nil {
		if logger != nil {
			logger.Warn("failed to process pattern result", "error", err)
		}
	} else if err := common.UpdateMetricOutputRef(ctx, result.MetricDocID, "Book", j.Book.BookID, writeResult.CID); err != nil {
		if logger != nil {
			logger.Warn("failed to update metric output ref", "error", err)
		}
	}

	return j.transitionToFinalizeDiscover(ctx), nil
}

// processFinalizePatternResult parses and stores pattern analysis results.
func (j *Job) processFinalizePatternResult(ctx context.Context, result jobs.WorkResult) (defra.WriteResult, error) {
	if result.ChatResult == nil {
		return defra.WriteResult{}, fmt.Errorf("no chat result")
	}

	var content []byte
	if len(result.ChatResult.ParsedJSON) > 0 {
		content = result.ChatResult.ParsedJSON
	} else if result.ChatResult.Content != "" {
		content = []byte(result.ChatResult.Content)
	} else {
		return defra.WriteResult{}, fmt.Errorf("empty response")
	}

	var response pattern_analyzer.Result
	if err := json.Unmarshal(content, &response); err != nil {
		return defra.WriteResult{}, fmt.Errorf("failed to parse pattern response: %w", err)
	}

	// Build result locally before storing in BookState
	patternResult := &common.FinalizePatternResult{
		Reasoning: response.Reasoning,
	}

	// Convert patterns, then fail closed on malformed model control data before
	// it can synthesize discovery agents or durable TocEntry records.
	var proposedPatterns []common.DiscoveredPattern
	for _, p := range response.DiscoveredPatterns {
		proposedPatterns = append(proposedPatterns, common.DiscoveredPattern{
			PatternType:   p.PatternType,
			LevelName:     p.LevelName,
			HeadingFormat: p.HeadingFormat,
			RangeStart:    p.RangeStart,
			RangeEnd:      p.RangeEnd,
			Level:         p.Level,
			Reasoning:     p.Reasoning,
		})
	}
	patternResult.Patterns = sanitizeDiscoveredPatternsWithCandidates(
		proposedPatterns, j.loadCandidateHeadings(),
	)
	if len(patternResult.Patterns) != len(proposedPatterns) {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("discarded malformed discovered patterns",
				"book_id", j.Book.BookID,
				"received", len(proposedPatterns),
				"accepted", len(patternResult.Patterns))
		}
	}

	// Convert model-produced exclusions, then enforce deterministic safety
	// boundaries before they can suppress discovery or influence link prompts.
	var proposedExcluded []common.ExcludedRange
	for _, e := range response.ExcludedRanges {
		proposedExcluded = append(proposedExcluded, common.ExcludedRange{
			StartPage: e.StartPage,
			EndPage:   e.EndPage,
			Reason:    e.Reason,
		})
	}
	patternResult.Excluded = sanitizeExcludedRanges(j.Book.TotalPages, proposedExcluded)
	if len(patternResult.Excluded) != len(proposedExcluded) {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("discarded unsafe pattern exclusions",
				"book_id", j.Book.BookID,
				"received", len(proposedExcluded),
				"accepted", len(patternResult.Excluded))
		}
	}

	// Store in BookState atomically
	j.Book.SetFinalizePatternResult(patternResult)

	// Generate entries to find
	j.generateEntriesToFind(ctx)

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		result := j.Book.GetFinalizePatternResult()
		logger.Info("pattern analysis complete",
			"patterns_found", len(result.Patterns),
			"excluded_ranges", len(result.Excluded),
			"entries_to_find", j.Book.GetEntriesToFindCount())
	}

	// Persist pattern results - return error to allow retry on failure
	writeResult, err := j.persistFinalizePatternResults(ctx)
	if err != nil {
		if logger != nil {
			logger.Error("failed to persist pattern results", "error", err)
		}
		return defra.WriteResult{}, fmt.Errorf("failed to persist pattern results: %w", err)
	}

	return writeResult, nil
}

// generateEntriesToFind creates EntryToFind records from discovered patterns.
func (j *Job) generateEntriesToFind(ctx context.Context) {
	if j.Book.GetFinalizePatternResult() == nil {
		return
	}

	// Get linked entries for comparison
	entries, _ := common.GetOrLoadLinkedEntries(ctx, j.Book, j.TocDocID)

	// Build sets of normalized existing identifiers. Models commonly mix Arabic,
	// Roman, and spelled-out numbers ("1", "I", "ONE"); exact strings would
	// rediscover an entry that is already present in the extracted ToC.
	existingIdentifiers := make(map[string]bool)
	existingAnyLevel := make(map[string]bool)
	for _, entry := range entries {
		identifier := normalizeSequenceIdentifier(entry.EntryNumber)
		if identifier == "" {
			continue
		}
		existingAnyLevel[identifier] = true
		if level := strings.ToLower(strings.TrimSpace(entry.LevelName)); level != "" {
			existingIdentifiers[level+"_"+identifier] = true
		}
	}

	// Clear previous entries
	j.Book.SetEntriesToFind(nil)

	// Generate entries from patterns
	for _, pattern := range j.Book.GetFinalizePatternResult().Patterns {
		identifiers := generateSequence(pattern.RangeStart, pattern.RangeEnd)
		level := strings.ToLower(strings.TrimSpace(pattern.LevelName))

		for i, identifier := range identifiers {
			normalizedIdentifier := normalizeSequenceIdentifier(identifier)
			if normalizedIdentifier == "" {
				continue
			}
			key := level + "_" + normalizedIdentifier

			if existingIdentifiers[key] || (level == "" && existingAnyLevel[normalizedIdentifier]) {
				continue
			}

			expectedPage := j.estimatePageLocation(entries, pattern, identifier, i, len(identifiers))

			searchStart := expectedPage - 20
			if searchStart < j.Book.GetBodyStart() {
				searchStart = j.Book.GetBodyStart()
			}
			searchEnd := expectedPage + 20
			if searchEnd > j.Book.GetBodyEnd() {
				searchEnd = j.Book.GetBodyEnd()
			}

			j.Book.AppendEntryToFind(&common.EntryToFind{
				Key:              key,
				LevelName:        pattern.LevelName,
				Identifier:       identifier,
				HeadingFormat:    pattern.HeadingFormat,
				Level:            pattern.Level,
				ExpectedNearPage: expectedPage,
				SearchRangeStart: searchStart,
				SearchRangeEnd:   searchEnd,
			})
		}
	}
}

func (j *Job) loadCandidateHeadings() []*candidateHeading {
	var candidates []*candidateHeading

	for pageNum := j.Book.GetBodyStart(); pageNum <= j.Book.GetBodyEnd(); pageNum++ {
		pageState := j.Book.GetPage(pageNum)
		if pageState == nil {
			continue
		}

		headings := pageState.GetHeadings()
		for _, h := range headings {
			if h.Text != "" {
				candidates = append(candidates, &candidateHeading{
					PageNum: pageNum,
					Text:    h.Text,
					Level:   h.Level,
				})
			}
		}
	}

	return candidates
}

func (j *Job) loadChapterStartPages(_ context.Context) ([]types.ChapterStartPage, error) {
	// Early pattern analysis has been removed - return nil.
	// Chapter start pages will be derived from linked ToC entries during finalize.
	return nil, nil
}

func (j *Job) convertEntriesForPattern(entries []*common.LinkedTocEntry) []pattern_analyzer.LinkedEntry {
	var result []pattern_analyzer.LinkedEntry
	for _, e := range entries {
		entry := pattern_analyzer.LinkedEntry{
			Title:       e.Title,
			EntryNumber: e.EntryNumber,
			Level:       e.Level,
			LevelName:   e.LevelName,
			ActualPage:  e.ActualPage,
		}
		result = append(result, entry)
	}
	return result
}

func (j *Job) convertCandidatesForPattern(candidates []*candidateHeading) []pattern_analyzer.CandidateHeading {
	var result []pattern_analyzer.CandidateHeading
	for _, c := range candidates {
		result = append(result, pattern_analyzer.CandidateHeading{
			PageNum: c.PageNum,
			Text:    c.Text,
			Level:   c.Level,
		})
	}
	return result
}

func (j *Job) convertDetectedChapters() []types.DetectedChapter {
	if j.FinalizePagePatternCtx == nil {
		return nil
	}
	return j.FinalizePagePatternCtx.ChapterPatterns
}

func (j *Job) persistFinalizePatternResults(ctx context.Context) (defra.WriteResult, error) {
	if j.Book.GetFinalizePatternResult() == nil {
		return defra.WriteResult{}, nil
	}

	data := struct {
		Patterns      []common.DiscoveredPattern `json:"patterns"`
		Excluded      []common.ExcludedRange     `json:"excluded_ranges"`
		EntriesToFind []*common.EntryToFind      `json:"entries_to_find"`
		Reasoning     string                     `json:"reasoning"`
	}{
		Patterns:      j.Book.GetFinalizePatternResult().Patterns,
		Excluded:      j.Book.GetFinalizePatternResult().Excluded,
		EntriesToFind: j.Book.GetEntriesToFind(),
		Reasoning:     j.Book.GetFinalizePatternResult().Reasoning,
	}

	jsonBytes, err := json.Marshal(data)
	if err != nil {
		return defra.WriteResult{}, fmt.Errorf("failed to marshal pattern analysis: %w", err)
	}

	// Use sync write for pattern results - this data is critical for restart
	writeResult, err := common.SendTracked(ctx, j.Book, defra.WriteOp{
		Collection: "Book",
		DocID:      j.Book.BookID,
		Document: map[string]any{
			"pattern_analysis_json": string(jsonBytes),
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return defra.WriteResult{}, fmt.Errorf("failed to persist pattern results: %w", err)
	}

	return writeResult, nil
}
