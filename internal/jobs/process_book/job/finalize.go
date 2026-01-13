package job

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"unicode"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	pattern_analyzer "github.com/jackzampolin/shelf/internal/agents/pattern_analyzer"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
	"github.com/jackzampolin/shelf/internal/types"
)

// MaxFinalizeRetries is the maximum number of retries for finalize operations.
const MaxFinalizeRetries = 3

// MinGapSize is the minimum number of pages to consider a gap significant.
const MinGapSize = 15

// FinalizeState holds in-memory state for finalize operations.
// This is created when finalize starts and lives on the Job struct.
type FinalizeState struct {
	// Pattern analysis results
	PatternResult *common.FinalizePatternResult

	// Page pattern context (loaded from page pattern analysis and labels)
	PagePatternCtx *PagePatternContext

	// Discover phase agents
	DiscoverAgents map[string]*agent.Agent // entryKey -> agent

	// Validate phase agents
	GapAgents map[string]*agent.Agent // gapKey -> agent
}

// PagePatternContext holds page pattern analysis data for enhanced ToC finalization.
type PagePatternContext struct {
	BodyStartPage   int
	BodyEndPage     int
	HasBoundaries   bool
	ChapterPatterns []types.DetectedChapter
}

// StartFinalizePhase initializes and starts the finalize phase.
// Returns the first work units to process.
func (j *Job) StartFinalizePhase(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Mark finalize as started
	if err := j.Book.TocFinalize.Start(); err != nil {
		if logger != nil {
			logger.Debug("finalize already started", "error", err)
		}
		return nil
	}
	common.PersistTocFinalizeState(ctx, j.TocDocID, &j.Book.TocFinalize)

	// Load linked entries (uses cache if available)
	entries, err := common.GetOrLoadLinkedEntries(ctx, j.Book, j.TocDocID)
	if err != nil {
		if logger != nil {
			logger.Error("failed to load linked entries for finalize",
				"book_id", j.Book.BookID,
				"error", err)
		}
		j.Book.TocFinalize.Fail(MaxBookOpRetries)
		common.PersistTocFinalizeState(ctx, j.TocDocID, &j.Book.TocFinalize)
		return nil
	}

	// Initialize finalize state
	j.FinalizeState = &FinalizeState{
		DiscoverAgents: make(map[string]*agent.Agent),
		GapAgents:      make(map[string]*agent.Agent),
	}

	// Build page pattern context
	j.FinalizeState.PagePatternCtx = buildPagePatternContext(j.Book)

	// Set body range: prefer page pattern analysis, fall back to ToC entries, then full book
	if j.FinalizeState.PagePatternCtx.HasBoundaries {
		j.Book.BodyStart = j.FinalizeState.PagePatternCtx.BodyStartPage
		j.Book.BodyEnd = j.FinalizeState.PagePatternCtx.BodyEndPage
	} else {
		var minPage, maxPage int
		for _, entry := range entries {
			if entry.ActualPage != nil {
				page := *entry.ActualPage
				if minPage == 0 || page < minPage {
					minPage = page
				}
				if page > maxPage {
					maxPage = page
				}
			}
		}
		if minPage > 0 && maxPage > 0 {
			j.Book.BodyStart = minPage
			j.Book.BodyEnd = maxPage
		} else {
			j.Book.BodyStart = 1
			j.Book.BodyEnd = j.Book.TotalPages
		}
	}

	// Set phase and persist
	j.Book.FinalizePhase = FinalizePhasePattern

	if logger != nil {
		linkedCount := 0
		for _, e := range entries {
			if e.ActualPage != nil {
				linkedCount++
			}
		}
		logger.Info("starting finalize phase",
			"book_id", j.Book.BookID,
			"entries_count", len(entries),
			"linked_count", linkedCount,
			"phase", FinalizePhasePattern)
	}

	// Create pattern analysis work unit
	unit, err := j.CreateFinalizePatternWorkUnit(ctx)
	if err != nil {
		if logger != nil {
			logger.Error("failed to create pattern work unit", "error", err)
		}
		return j.transitionToFinalizeDiscover(ctx)
	}

	if unit == nil {
		// No work to do - skip to completion
		return j.completeFinalizePhase(ctx)
	}

	return []jobs.WorkUnit{*unit}
}

// CreateFinalizePatternWorkUnit creates a work unit for pattern analysis.
func (j *Job) CreateFinalizePatternWorkUnit(ctx context.Context) (*jobs.WorkUnit, error) {
	// Load candidate headings from Page.headings
	candidates := j.loadCandidateHeadings()

	// Load chapter start pages from labels
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
		if j.FinalizeState != nil && j.FinalizeState.PagePatternCtx != nil {
			detectedCount = len(j.FinalizeState.PagePatternCtx.ChapterPatterns)
		}
		logger.Info("pattern analysis context loaded",
			"candidate_count", len(candidates),
			"detected_chapters", detectedCount,
			"chapter_start_pages", len(chapterStartPages),
			"body_start", j.Book.BodyStart,
			"body_end", j.Book.BodyEnd,
			"linked_entries", len(entries))
	}

	// Build prompts with enhanced context
	systemPrompt := j.GetPrompt(pattern_analyzer.PromptKey)
	userPrompt := pattern_analyzer.BuildUserPrompt(pattern_analyzer.UserPromptData{
		LinkedEntries:     j.convertEntriesForPattern(entries),
		Candidates:        j.convertCandidatesForPattern(candidates),
		DetectedChapters:  j.convertDetectedChapters(),
		ChapterStartPages: chapterStartPages,
		BodyStart:         j.Book.BodyStart,
		BodyEnd:           j.Book.BodyEnd,
		TotalPages:        j.Book.TotalPages,
	})

	// Create chat request with structured output
	schemaBytes, err := json.Marshal(pattern_analyzer.JSONSchema())
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
			logger.Info("pattern analysis permanently failed, skipping to discover")
		}
		return j.transitionToFinalizeDiscover(ctx), nil
	}

	// Process pattern analysis result
	if err := j.processFinalizePatternResult(ctx, result); err != nil {
		if logger != nil {
			logger.Warn("failed to process pattern result", "error", err)
		}
	}

	return j.transitionToFinalizeDiscover(ctx), nil
}

// processFinalizePatternResult parses and stores pattern analysis results.
func (j *Job) processFinalizePatternResult(ctx context.Context, result jobs.WorkResult) error {
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

	var response pattern_analyzer.Result
	if err := json.Unmarshal(content, &response); err != nil {
		return fmt.Errorf("failed to parse pattern response: %w", err)
	}

	// Store in BookState
	j.Book.FinalizePatternResult = &common.FinalizePatternResult{
		Reasoning: response.Reasoning,
	}

	// Convert patterns
	for _, p := range response.DiscoveredPatterns {
		j.Book.FinalizePatternResult.Patterns = append(j.Book.FinalizePatternResult.Patterns, common.DiscoveredPattern{
			PatternType:   p.PatternType,
			LevelName:     p.LevelName,
			HeadingFormat: p.HeadingFormat,
			RangeStart:    p.RangeStart,
			RangeEnd:      p.RangeEnd,
			Level:         p.Level,
			Reasoning:     p.Reasoning,
		})
	}

	// Convert excluded ranges
	for _, e := range response.ExcludedRanges {
		j.Book.FinalizePatternResult.Excluded = append(j.Book.FinalizePatternResult.Excluded, common.ExcludedRange{
			StartPage: e.StartPage,
			EndPage:   e.EndPage,
			Reason:    e.Reason,
		})
	}

	// Also store in FinalizeState for runtime access
	if j.FinalizeState != nil {
		j.FinalizeState.PatternResult = j.Book.FinalizePatternResult
	}

	// Generate entries to find
	j.generateEntriesToFind(ctx)

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("pattern analysis complete",
			"patterns_found", len(j.Book.FinalizePatternResult.Patterns),
			"excluded_ranges", len(j.Book.FinalizePatternResult.Excluded),
			"entries_to_find", len(j.Book.EntriesToFind))
	}

	// Persist pattern results
	if err := j.persistFinalizePatternResults(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to persist pattern results", "error", err)
		}
	}

	return nil
}

// generateEntriesToFind creates EntryToFind records from discovered patterns.
func (j *Job) generateEntriesToFind(ctx context.Context) {
	if j.Book.FinalizePatternResult == nil {
		return
	}

	// Get linked entries for comparison
	entries, _ := common.GetOrLoadLinkedEntries(ctx, j.Book, j.TocDocID)

	// Build a set of existing entry identifiers
	existingIdentifiers := make(map[string]bool)
	for _, entry := range entries {
		if entry.LevelName != "" && entry.EntryNumber != "" {
			key := strings.ToLower(entry.LevelName + "_" + entry.EntryNumber)
			existingIdentifiers[key] = true
		}
	}

	// Clear previous entries
	j.Book.EntriesToFind = nil

	// Generate entries from patterns
	for _, pattern := range j.Book.FinalizePatternResult.Patterns {
		identifiers := generateSequence(pattern.RangeStart, pattern.RangeEnd)

		for i, identifier := range identifiers {
			key := strings.ToLower(pattern.LevelName + "_" + identifier)

			if existingIdentifiers[key] {
				continue
			}

			expectedPage := j.estimatePageLocation(entries, pattern, identifier, i, len(identifiers))

			searchStart := expectedPage - 20
			if searchStart < j.Book.BodyStart {
				searchStart = j.Book.BodyStart
			}
			searchEnd := expectedPage + 20
			if searchEnd > j.Book.BodyEnd {
				searchEnd = j.Book.BodyEnd
			}

			j.Book.EntriesToFind = append(j.Book.EntriesToFind, &common.EntryToFind{
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

// transitionToFinalizeDiscover moves to the discover phase.
func (j *Job) transitionToFinalizeDiscover(ctx context.Context) []jobs.WorkUnit {
	j.Book.FinalizePhase = FinalizePhaseDiscover

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("transitioning to discover phase",
			"book_id", j.Book.BookID,
			"entries_to_find", len(j.Book.EntriesToFind))
	}

	if len(j.Book.EntriesToFind) == 0 {
		return j.transitionToFinalizeValidate(ctx)
	}

	return j.createFinalizeDiscoverWorkUnits(ctx)
}

// createFinalizeDiscoverWorkUnits creates work units for all entries to discover.
func (j *Job) createFinalizeDiscoverWorkUnits(ctx context.Context) []jobs.WorkUnit {
	var units []jobs.WorkUnit

	for _, entry := range j.Book.EntriesToFind {
		unit := j.createChapterFinderWorkUnit(ctx, entry)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units
}

// createChapterFinderWorkUnit creates a chapter finder agent work unit.
func (j *Job) createChapterFinderWorkUnit(ctx context.Context, entry *common.EntryToFind) *jobs.WorkUnit {
	var excludedRanges []chapter_finder.ExcludedRange
	if j.Book.FinalizePatternResult != nil {
		for _, ex := range j.Book.FinalizePatternResult.Excluded {
			excludedRanges = append(excludedRanges, chapter_finder.ExcludedRange{
				StartPage: ex.StartPage,
				EndPage:   ex.EndPage,
				Reason:    ex.Reason,
			})
		}
	}

	agentEntry := &chapter_finder.EntryToFind{
		LevelName:        entry.LevelName,
		Identifier:       entry.Identifier,
		HeadingFormat:    entry.HeadingFormat,
		ExpectedNearPage: entry.ExpectedNearPage,
		SearchRangeStart: entry.SearchRangeStart,
		SearchRangeEnd:   entry.SearchRangeEnd,
	}

	ag := agents.NewChapterFinderAgent(ctx, agents.ChapterFinderConfig{
		Book:           j.Book,
		SystemPrompt:   j.GetPrompt(chapter_finder.PromptKey),
		Entry:          agentEntry,
		ExcludedRanges: excludedRanges,
		Debug:          j.Book.DebugAgents,
		JobID:          j.RecordID,
	})

	if j.FinalizeState != nil {
		j.FinalizeState.DiscoverAgents[entry.Key] = ag
	}

	agentUnits := agents.ExecuteToolLoop(ctx, ag)
	if len(agentUnits) == 0 {
		return nil
	}

	jobUnits := j.convertDiscoverAgentUnits(agentUnits, entry.Key)
	if len(jobUnits) == 0 {
		return nil
	}

	return &jobUnits[0]
}

// HandleFinalizeDiscoverComplete processes chapter finder completion.
func (j *Job) HandleFinalizeDiscoverComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	logger := svcctx.LoggerFrom(ctx)

	if j.FinalizeState == nil {
		return nil, fmt.Errorf("finalize state not initialized")
	}

	ag, ok := j.FinalizeState.DiscoverAgents[info.FinalizeKey]
	if !ok {
		j.RemoveWorkUnit(result.WorkUnitID)
		j.Book.FinalizeEntriesComplete++
		return j.checkFinalizeDiscoverCompletion(ctx), nil
	}

	if !result.Success {
		if info.RetryCount < MaxFinalizeRetries {
			if logger != nil {
				logger.Warn("chapter finder failed, retrying",
					"entry_key", info.FinalizeKey,
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			return j.retryFinalizeDiscoverUnit(ctx, info)
		}
		j.Book.FinalizeEntriesComplete++
		j.RemoveWorkUnit(result.WorkUnitID)
		if logger != nil {
			logger.Warn("chapter finder permanently failed",
				"entry_key", info.FinalizeKey,
				"error", result.Error)
		}
		return j.checkFinalizeDiscoverCompletion(ctx), nil
	}

	// Handle LLM result
	if result.ChatResult != nil {
		ag.HandleLLMResult(result.ChatResult)

		agentUnits := agents.ExecuteToolLoop(ctx, ag)
		if len(agentUnits) > 0 {
			return j.convertDiscoverAgentUnits(agentUnits, info.FinalizeKey), nil
		}
	}

	// Check if agent is done
	if ag.IsDone() {
		if err := ag.SaveLog(ctx); err != nil {
			if logger != nil {
				logger.Warn("failed to save agent log", "error", err)
			}
		}

		agentResult := ag.Result()
		if agentResult != nil && agentResult.Success {
			if finderResult, ok := agentResult.ToolResult.(*chapter_finder.Result); ok {
				if err := j.saveDiscoveredEntry(ctx, info.FinalizeKey, finderResult); err != nil {
					if logger != nil {
						logger.Warn("failed to save discovered entry", "error", err)
					}
				}
				if finderResult.ScanPage != nil && *finderResult.ScanPage > 0 {
					j.Book.FinalizeEntriesFound++
				}
			}
		}

		j.Book.FinalizeEntriesComplete++
		delete(j.FinalizeState.DiscoverAgents, info.FinalizeKey)
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	return j.checkFinalizeDiscoverCompletion(ctx), nil
}

// checkFinalizeDiscoverCompletion checks if discover phase is complete.
func (j *Job) checkFinalizeDiscoverCompletion(ctx context.Context) []jobs.WorkUnit {
	if j.Book.FinalizeEntriesComplete >= len(j.Book.EntriesToFind) {
		return j.transitionToFinalizeValidate(ctx)
	}
	return nil
}

// transitionToFinalizeValidate moves to the validate phase.
func (j *Job) transitionToFinalizeValidate(ctx context.Context) []jobs.WorkUnit {
	j.Book.FinalizePhase = FinalizePhaseValidate

	// Find gaps in page coverage
	if err := j.findFinalizeGaps(ctx); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to find gaps", "error", err)
		}
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("transitioning to validate phase",
			"book_id", j.Book.BookID,
			"gaps", len(j.Book.FinalizeGaps))
	}

	if len(j.Book.FinalizeGaps) == 0 {
		return j.completeFinalizePhase(ctx)
	}

	return j.createFinalizeGapWorkUnits(ctx)
}

// findFinalizeGaps identifies gaps in page coverage.
func (j *Job) findFinalizeGaps(ctx context.Context) error {
	// Refresh linked entries to include discoveries
	entries, err := common.RefreshLinkedEntries(ctx, j.Book, j.TocDocID)
	if err != nil {
		return err
	}

	// Sort entries by actual page
	sortedEntries := make([]*common.LinkedTocEntry, 0, len(entries))
	for _, e := range entries {
		if e.ActualPage != nil {
			sortedEntries = append(sortedEntries, e)
		}
	}
	sort.Slice(sortedEntries, func(i, k int) bool {
		return *sortedEntries[i].ActualPage < *sortedEntries[k].ActualPage
	})

	// Clear previous gaps
	j.Book.FinalizeGaps = nil

	// Check gap from body start to first entry
	if len(sortedEntries) > 0 {
		first := sortedEntries[0]
		if *first.ActualPage-j.Book.BodyStart > MinGapSize {
			j.Book.FinalizeGaps = append(j.Book.FinalizeGaps, &common.FinalizeGap{
				Key:            fmt.Sprintf("gap_%d_%d", j.Book.BodyStart, *first.ActualPage-1),
				StartPage:      j.Book.BodyStart,
				EndPage:        *first.ActualPage - 1,
				Size:           *first.ActualPage - j.Book.BodyStart,
				NextEntryTitle: first.Title,
				NextEntryPage:  *first.ActualPage,
			})
		}
	}

	// Check gaps between consecutive entries
	for i := 0; i < len(sortedEntries)-1; i++ {
		curr := sortedEntries[i]
		next := sortedEntries[i+1]

		gapSize := *next.ActualPage - *curr.ActualPage
		if gapSize > MinGapSize {
			if j.isPageExcluded(*curr.ActualPage + 1) {
				continue
			}

			j.Book.FinalizeGaps = append(j.Book.FinalizeGaps, &common.FinalizeGap{
				Key:            fmt.Sprintf("gap_%d_%d", *curr.ActualPage+1, *next.ActualPage-1),
				StartPage:      *curr.ActualPage + 1,
				EndPage:        *next.ActualPage - 1,
				Size:           gapSize - 1,
				PrevEntryTitle: curr.Title,
				PrevEntryPage:  *curr.ActualPage,
				NextEntryTitle: next.Title,
				NextEntryPage:  *next.ActualPage,
			})
		}
	}

	// Check gap from last entry to body end
	if len(sortedEntries) > 0 {
		last := sortedEntries[len(sortedEntries)-1]
		if j.Book.BodyEnd-*last.ActualPage > MinGapSize && !j.isPageExcluded(*last.ActualPage+1) {
			j.Book.FinalizeGaps = append(j.Book.FinalizeGaps, &common.FinalizeGap{
				Key:            fmt.Sprintf("gap_%d_%d", *last.ActualPage+1, j.Book.BodyEnd),
				StartPage:      *last.ActualPage + 1,
				EndPage:        j.Book.BodyEnd,
				Size:           j.Book.BodyEnd - *last.ActualPage,
				PrevEntryTitle: last.Title,
				PrevEntryPage:  *last.ActualPage,
			})
		}
	}

	return nil
}

// isPageExcluded checks if a page is in an excluded range.
func (j *Job) isPageExcluded(page int) bool {
	if j.Book.FinalizePatternResult == nil {
		return false
	}
	for _, ex := range j.Book.FinalizePatternResult.Excluded {
		if page >= ex.StartPage && page <= ex.EndPage {
			return true
		}
	}
	return false
}

// createFinalizeGapWorkUnits creates work units for gap investigation.
func (j *Job) createFinalizeGapWorkUnits(ctx context.Context) []jobs.WorkUnit {
	var units []jobs.WorkUnit

	for _, gap := range j.Book.FinalizeGaps {
		unit := j.createGapInvestigatorWorkUnit(ctx, gap)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units
}

// createGapInvestigatorWorkUnit creates a gap investigator agent work unit.
func (j *Job) createGapInvestigatorWorkUnit(ctx context.Context, gap *common.FinalizeGap) *jobs.WorkUnit {
	agentGap := &gap_investigator.GapInfo{
		StartPage:      gap.StartPage,
		EndPage:        gap.EndPage,
		Size:           gap.Size,
		PrevEntryTitle: gap.PrevEntryTitle,
		PrevEntryPage:  gap.PrevEntryPage,
		NextEntryTitle: gap.NextEntryTitle,
		NextEntryPage:  gap.NextEntryPage,
	}

	// Get linked entries
	entries, _ := common.GetOrLoadLinkedEntries(ctx, j.Book, j.TocDocID)
	var linkedEntries []*gap_investigator.LinkedEntry
	for _, e := range entries {
		if e.ActualPage != nil {
			linkedEntries = append(linkedEntries, &gap_investigator.LinkedEntry{
				DocID:      e.DocID,
				Title:      e.Title,
				Level:      e.Level,
				LevelName:  e.LevelName,
				ActualPage: *e.ActualPage,
			})
		}
	}

	ag := agents.NewGapInvestigatorAgent(ctx, agents.GapInvestigatorConfig{
		Book:          j.Book,
		SystemPrompt:  j.GetPrompt(gap_investigator.PromptKey),
		Gap:           agentGap,
		LinkedEntries: linkedEntries,
		Debug:         j.Book.DebugAgents,
		JobID:         j.RecordID,
	})

	if j.FinalizeState != nil {
		j.FinalizeState.GapAgents[gap.Key] = ag
	}

	agentUnits := agents.ExecuteToolLoop(ctx, ag)
	if len(agentUnits) == 0 {
		return nil
	}

	jobUnits := j.convertGapAgentUnits(agentUnits, gap.Key)
	if len(jobUnits) == 0 {
		return nil
	}

	return &jobUnits[0]
}

// HandleFinalizeGapComplete processes gap investigator completion.
func (j *Job) HandleFinalizeGapComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	logger := svcctx.LoggerFrom(ctx)

	if j.FinalizeState == nil {
		return nil, fmt.Errorf("finalize state not initialized")
	}

	ag, ok := j.FinalizeState.GapAgents[info.FinalizeKey]
	if !ok {
		j.RemoveWorkUnit(result.WorkUnitID)
		j.Book.FinalizeGapsComplete++
		return j.checkFinalizeValidateCompletion(ctx), nil
	}

	if !result.Success {
		if info.RetryCount < MaxFinalizeRetries {
			if logger != nil {
				logger.Warn("gap investigator failed, retrying",
					"gap_key", info.FinalizeKey,
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			return j.retryFinalizeGapUnit(ctx, info)
		}
		j.Book.FinalizeGapsComplete++
		j.RemoveWorkUnit(result.WorkUnitID)
		if logger != nil {
			logger.Warn("gap investigator permanently failed",
				"gap_key", info.FinalizeKey,
				"error", result.Error)
		}
		return j.checkFinalizeValidateCompletion(ctx), nil
	}

	// Handle LLM result
	if result.ChatResult != nil {
		ag.HandleLLMResult(result.ChatResult)

		agentUnits := agents.ExecuteToolLoop(ctx, ag)
		if len(agentUnits) > 0 {
			return j.convertGapAgentUnits(agentUnits, info.FinalizeKey), nil
		}
	}

	// Check if agent is done
	if ag.IsDone() {
		if err := ag.SaveLog(ctx); err != nil {
			if logger != nil {
				logger.Warn("failed to save agent log", "error", err)
			}
		}

		agentResult := ag.Result()
		if agentResult != nil && agentResult.Success {
			if gapResult, ok := agentResult.ToolResult.(*gap_investigator.Result); ok {
				if err := j.applyGapFix(ctx, info.FinalizeKey, gapResult); err != nil {
					if logger != nil {
						logger.Warn("failed to apply gap fix", "error", err)
					}
				}
				if gapResult.FixType == "add_entry" || gapResult.FixType == "correct_entry" {
					j.Book.FinalizeGapsFixes++
				}
			}
		}

		j.Book.FinalizeGapsComplete++
		delete(j.FinalizeState.GapAgents, info.FinalizeKey)
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	return j.checkFinalizeValidateCompletion(ctx), nil
}

// checkFinalizeValidateCompletion checks if validate phase is complete.
func (j *Job) checkFinalizeValidateCompletion(ctx context.Context) []jobs.WorkUnit {
	if j.Book.FinalizeGapsComplete >= len(j.Book.FinalizeGaps) {
		return j.completeFinalizePhase(ctx)
	}
	return nil
}

// completeFinalizePhase marks finalize as complete and transitions to structure.
func (j *Job) completeFinalizePhase(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Re-sort all TocEntries by actual_page
	if err := j.resortEntriesByPage(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to re-sort entries by page", "error", err)
		}
	}

	j.Book.FinalizePhase = FinalizePhaseDone
	j.Book.TocFinalize.Complete()
	common.PersistTocFinalizeState(ctx, j.TocDocID, &j.Book.TocFinalize)

	if logger != nil {
		logger.Info("finalize phase complete",
			"book_id", j.Book.BookID,
			"entries_found", j.Book.FinalizeEntriesFound,
			"gaps_fixed", j.Book.FinalizeGapsFixes)
	}

	// Continue to structure
	return j.MaybeStartStructureInline(ctx)
}

// Helper functions

func buildPagePatternContext(book *common.BookState) *PagePatternContext {
	ctx := &PagePatternContext{}

	if book.PatternAnalysisResult != nil {
		par := book.PatternAnalysisResult

		if par.BodyBoundaries != nil {
			ctx.BodyStartPage = par.BodyBoundaries.BodyStartPage
			if par.BodyBoundaries.BodyEndPage != nil {
				ctx.BodyEndPage = *par.BodyBoundaries.BodyEndPage
			} else {
				ctx.BodyEndPage = book.TotalPages
			}
			ctx.HasBoundaries = true
		}

		for _, cp := range par.ChapterPatterns {
			detected := types.DetectedChapter{
				PageNum:       cp.StartPage,
				RunningHeader: cp.RunningHeader,
				ChapterTitle:  cp.ChapterTitle,
				ChapterNumber: cp.ChapterNumber,
				Source:        types.SourcePatternAnalysis,
				Confidence:    types.ParseConfidenceLevel(cp.Confidence),
			}
			ctx.ChapterPatterns = append(ctx.ChapterPatterns, detected)
		}
	}

	return ctx
}

func (j *Job) loadCandidateHeadings() []*candidateHeading {
	var candidates []*candidateHeading

	for pageNum := j.Book.BodyStart; pageNum <= j.Book.BodyEnd; pageNum++ {
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

type candidateHeading struct {
	PageNum int
	Text    string
	Level   int
}

func (j *Job) loadChapterStartPages(ctx context.Context) ([]types.ChapterStartPage, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, is_chapter_start: {_eq: true}}, order: {page_num: ASC}) {
			page_num
			running_header
		}
	}`, j.Book.BookDocID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query chapter start pages: %w", err)
	}

	rawPages, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil, nil
	}

	var result []types.ChapterStartPage
	for _, p := range rawPages {
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}

		csp := types.ChapterStartPage{}
		if pageNum, ok := page["page_num"].(float64); ok {
			csp.PageNum = int(pageNum)
		}
		if rh, ok := page["running_header"].(string); ok {
			csp.RunningHeader = rh
		}

		if csp.PageNum > 0 {
			result = append(result, csp)
		}
	}

	return result, nil
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
	if j.FinalizeState == nil || j.FinalizeState.PagePatternCtx == nil {
		return nil
	}
	return j.FinalizeState.PagePatternCtx.ChapterPatterns
}

func (j *Job) estimatePageLocation(entries []*common.LinkedTocEntry, pattern common.DiscoveredPattern, identifier string, index, total int) int {
	var beforePage, afterPage int
	beforeFound, afterFound := false, false

	for _, entry := range entries {
		if entry.ActualPage == nil || entry.LevelName != pattern.LevelName {
			continue
		}

		cmp := compareIdentifiers(entry.EntryNumber, identifier)
		if cmp < 0 && *entry.ActualPage > beforePage {
			beforePage = *entry.ActualPage
			beforeFound = true
		} else if cmp > 0 && (!afterFound || *entry.ActualPage < afterPage) {
			afterPage = *entry.ActualPage
			afterFound = true
		}
	}

	if beforeFound && afterFound {
		return beforePage + (afterPage-beforePage)/2
	} else if beforeFound {
		return beforePage + 10
	} else if afterFound {
		return afterPage - 10
	}

	bodyRange := j.Book.BodyEnd - j.Book.BodyStart
	if total > 0 {
		return j.Book.BodyStart + (bodyRange * index / total)
	}
	return j.Book.BodyStart + bodyRange/2
}

func compareIdentifiers(a, b string) int {
	aNum, aErr := strconv.Atoi(a)
	bNum, bErr := strconv.Atoi(b)
	if aErr == nil && bErr == nil {
		if aNum < bNum {
			return -1
		} else if aNum > bNum {
			return 1
		}
		return 0
	}

	aRoman := romanToInt(strings.ToUpper(a))
	bRoman := romanToInt(strings.ToUpper(b))
	if aRoman > 0 && bRoman > 0 {
		if aRoman < bRoman {
			return -1
		} else if aRoman > bRoman {
			return 1
		}
		return 0
	}

	return strings.Compare(strings.ToLower(a), strings.ToLower(b))
}

func generateSequence(start, end string) []string {
	startNum, startErr := strconv.Atoi(start)
	endNum, endErr := strconv.Atoi(end)
	if startErr == nil && endErr == nil {
		var result []string
		for i := startNum; i <= endNum; i++ {
			result = append(result, strconv.Itoa(i))
		}
		return result
	}

	startRoman := romanToInt(strings.ToUpper(start))
	endRoman := romanToInt(strings.ToUpper(end))
	if startRoman > 0 && endRoman > 0 {
		var result []string
		for i := startRoman; i <= endRoman; i++ {
			result = append(result, intToRoman(i))
		}
		return result
	}

	return []string{start}
}

func romanToInt(s string) int {
	romanMap := map[byte]int{
		'I': 1, 'V': 5, 'X': 10, 'L': 50,
		'C': 100, 'D': 500, 'M': 1000,
	}

	result := 0
	for i := 0; i < len(s); i++ {
		val, ok := romanMap[s[i]]
		if !ok {
			return 0
		}
		if i+1 < len(s) && romanMap[s[i+1]] > val {
			result -= val
		} else {
			result += val
		}
	}
	return result
}

func intToRoman(num int) string {
	values := []int{1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1}
	symbols := []string{"M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"}

	var result strings.Builder
	for i := 0; i < len(values); i++ {
		for num >= values[i] {
			num -= values[i]
			result.WriteString(symbols[i])
		}
	}
	return result.String()
}

func (j *Job) persistFinalizePatternResults(ctx context.Context) error {
	if j.Book.FinalizePatternResult == nil {
		return nil
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	data := struct {
		Patterns      []common.DiscoveredPattern `json:"patterns"`
		Excluded      []common.ExcludedRange     `json:"excluded_ranges"`
		EntriesToFind []*common.EntryToFind      `json:"entries_to_find"`
		Reasoning     string                     `json:"reasoning"`
	}{
		Patterns:      j.Book.FinalizePatternResult.Patterns,
		Excluded:      j.Book.FinalizePatternResult.Excluded,
		EntriesToFind: j.Book.EntriesToFind,
		Reasoning:     j.Book.FinalizePatternResult.Reasoning,
	}

	jsonBytes, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("failed to marshal pattern analysis: %w", err)
	}

	sink.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      j.Book.BookID,
		Document: map[string]any{
			"pattern_analysis_json": string(jsonBytes),
		},
		Op: defra.OpUpdate,
	})

	return nil
}

func (j *Job) saveDiscoveredEntry(ctx context.Context, entryKey string, result *chapter_finder.Result) error {
	if result.ScanPage == nil || *result.ScanPage == 0 {
		return nil
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	var entry *common.EntryToFind
	for _, e := range j.Book.EntriesToFind {
		if e.Key == entryKey {
			entry = e
			break
		}
	}
	if entry == nil {
		return fmt.Errorf("entry not found: %s", entryKey)
	}

	pageDocID := j.getPageDocID(*result.ScanPage)
	sortOrder := *result.ScanPage * 1000
	title := fmt.Sprintf("%s %s", titleCase(entry.LevelName), entry.Identifier)
	uniqueKey := fmt.Sprintf("%s:discovered:%s", j.TocDocID, entryKey)

	entryData := map[string]any{
		"toc_id":       j.TocDocID,
		"unique_key":   uniqueKey,
		"entry_number": entry.Identifier,
		"title":        title,
		"level":        entry.Level,
		"level_name":   entry.LevelName,
		"sort_order":   sortOrder,
		"source":       "discovered",
	}

	if pageDocID != "" {
		entryData["actual_page_id"] = pageDocID
	}

	filter := map[string]any{
		"unique_key": map[string]any{"_eq": uniqueKey},
	}

	_, err := defraClient.Upsert(ctx, "TocEntry", filter, entryData, entryData)
	if err != nil {
		return fmt.Errorf("failed to upsert discovered entry: %w", err)
	}

	return nil
}

func titleCase(s string) string {
	if s == "" {
		return s
	}
	runes := []rune(s)
	runes[0] = unicode.ToUpper(runes[0])
	return string(runes)
}

func (j *Job) getPageDocID(pageNum int) string {
	state := j.Book.GetPage(pageNum)
	if state == nil {
		return ""
	}
	return state.GetPageDocID()
}

func (j *Job) applyGapFix(ctx context.Context, gapKey string, result *gap_investigator.Result) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	switch result.FixType {
	case "add_entry":
		if result.ScanPage == 0 {
			return nil
		}

		pageDocID := j.getPageDocID(result.ScanPage)
		sortOrder := result.ScanPage * 1000
		uniqueKey := fmt.Sprintf("%s:validated:%s", j.TocDocID, gapKey)

		entryData := map[string]any{
			"toc_id":     j.TocDocID,
			"unique_key": uniqueKey,
			"title":      result.Title,
			"level":      result.Level,
			"level_name": result.LevelName,
			"sort_order": sortOrder,
			"source":     "validated",
		}

		if pageDocID != "" {
			entryData["actual_page_id"] = pageDocID
		}

		filter := map[string]any{
			"unique_key": map[string]any{"_eq": uniqueKey},
		}

		if _, err := defraClient.Upsert(ctx, "TocEntry", filter, entryData, entryData); err != nil {
			return fmt.Errorf("failed to upsert validated entry: %w", err)
		}

	case "correct_entry":
		if result.EntryDocID == "" || result.ScanPage == 0 {
			return nil
		}

		pageDocID := j.getPageDocID(result.ScanPage)
		if pageDocID != "" {
			sink.Send(defra.WriteOp{
				Collection: "TocEntry",
				DocID:      result.EntryDocID,
				Document: map[string]any{
					"actual_page_id": pageDocID,
				},
				Op: defra.OpUpdate,
			})
		}

	case "flag_for_review":
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Info("gap flagged for review",
				"gap_key", gapKey,
				"reasoning", result.Reasoning)
		}

	case "no_fix_needed":
		// Nothing to do
	}

	return nil
}

func (j *Job) resortEntriesByPage(ctx context.Context) error {
	entries, err := common.RefreshLinkedEntries(ctx, j.Book, j.TocDocID)
	if err != nil {
		return fmt.Errorf("failed to load entries: %w", err)
	}

	if len(entries) == 0 {
		return nil
	}

	sort.Slice(entries, func(i, k int) bool {
		if entries[i].ActualPage == nil && entries[k].ActualPage == nil {
			return entries[i].SortOrder < entries[k].SortOrder
		}
		if entries[i].ActualPage == nil {
			return false
		}
		if entries[k].ActualPage == nil {
			return true
		}
		return *entries[i].ActualPage < *entries[k].ActualPage
	})

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	for i, entry := range entries {
		newSortOrder := (i + 1) * 100
		if entry.SortOrder != newSortOrder {
			sink.Send(defra.WriteOp{
				Collection: "TocEntry",
				DocID:      entry.DocID,
				Document: map[string]any{
					"sort_order": newSortOrder,
				},
				Op: defra.OpUpdate,
			})
		}
	}

	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		logger.Info("re-sorted ToC entries by page",
			"toc_doc_id", j.TocDocID,
			"entry_count", len(entries))
	}

	return nil
}

func (j *Job) convertDiscoverAgentUnits(agentUnits []agent.WorkUnit, entryKey string) []jobs.WorkUnit {
	jobUnits := agents.ConvertToJobUnits(agentUnits, agents.ConvertConfig{
		JobID:     j.RecordID,
		Provider:  j.Book.TocProvider,
		Stage:     "toc-discover",
		ItemKey:   fmt.Sprintf("discover_%s", entryKey),
		PromptKey: chapter_finder.PromptKey,
		PromptCID: j.GetPromptCID(chapter_finder.PromptKey),
		BookID:    j.Book.BookID,
	})

	for _, u := range jobUnits {
		j.RegisterWorkUnit(u.ID, WorkUnitInfo{
			UnitType:      WorkUnitTypeFinalizeDiscover,
			FinalizePhase: FinalizePhaseDiscover,
			FinalizeKey:   entryKey,
		})
	}

	return jobUnits
}

func (j *Job) convertGapAgentUnits(agentUnits []agent.WorkUnit, gapKey string) []jobs.WorkUnit {
	jobUnits := agents.ConvertToJobUnits(agentUnits, agents.ConvertConfig{
		JobID:     j.RecordID,
		Provider:  j.Book.TocProvider,
		Stage:     "toc-validate",
		ItemKey:   fmt.Sprintf("gap_%s", gapKey),
		PromptKey: gap_investigator.PromptKey,
		PromptCID: j.GetPromptCID(gap_investigator.PromptKey),
		BookID:    j.Book.BookID,
	})

	for _, u := range jobUnits {
		j.RegisterWorkUnit(u.ID, WorkUnitInfo{
			UnitType:      WorkUnitTypeFinalizeGap,
			FinalizePhase: FinalizePhaseValidate,
			FinalizeKey:   gapKey,
		})
	}

	return jobUnits
}

func (j *Job) retryFinalizeDiscoverUnit(ctx context.Context, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	var entry *common.EntryToFind
	for _, e := range j.Book.EntriesToFind {
		if e.Key == info.FinalizeKey {
			entry = e
			break
		}
	}
	if entry == nil {
		return nil, nil
	}

	if j.FinalizeState != nil {
		delete(j.FinalizeState.DiscoverAgents, info.FinalizeKey)
	}

	unit := j.createChapterFinderWorkUnit(ctx, entry)
	if unit != nil {
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			UnitType:      WorkUnitTypeFinalizeDiscover,
			FinalizePhase: FinalizePhaseDiscover,
			FinalizeKey:   info.FinalizeKey,
			RetryCount:    info.RetryCount + 1,
		})
		return []jobs.WorkUnit{*unit}, nil
	}

	return nil, nil
}

func (j *Job) retryFinalizeGapUnit(ctx context.Context, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	var gap *common.FinalizeGap
	for _, g := range j.Book.FinalizeGaps {
		if g.Key == info.FinalizeKey {
			gap = g
			break
		}
	}
	if gap == nil {
		return nil, nil
	}

	if j.FinalizeState != nil {
		delete(j.FinalizeState.GapAgents, info.FinalizeKey)
	}

	unit := j.createGapInvestigatorWorkUnit(ctx, gap)
	if unit != nil {
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			UnitType:      WorkUnitTypeFinalizeGap,
			FinalizePhase: FinalizePhaseValidate,
			FinalizeKey:   info.FinalizeKey,
			RetryCount:    info.RetryCount + 1,
		})
		return []jobs.WorkUnit{*unit}, nil
	}

	return nil, nil
}
