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

// PagePatternContext holds page pattern analysis data for enhanced ToC finalization.
// This is local to finalize phase execution.
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
	if err := j.Book.TocFinalizeStart(); err != nil {
		if logger != nil {
			logger.Debug("finalize already started", "error", err)
		}
		return nil
	}
	// Use sync write at operation start to ensure state is persisted before continuing
	tocFinalizeState := j.Book.GetTocFinalizeState()
	if err := common.PersistTocFinalizeStateSync(ctx, j.TocDocID, &tocFinalizeState); err != nil {
		if logger != nil {
			logger.Error("failed to persist finalize start", "error", err)
		}
		j.Book.TocFinalizeReset()
		return nil
	}

	// Load linked entries (uses cache if available)
	entries, err := common.GetOrLoadLinkedEntries(ctx, j.Book, j.TocDocID)
	if err != nil {
		if logger != nil {
			logger.Error("failed to load linked entries for finalize",
				"book_id", j.Book.BookID,
				"error", err)
		}
		j.Book.TocFinalizeFail(MaxBookOpRetries)
		tocFinalizeState := j.Book.GetTocFinalizeState()
		common.PersistTocFinalizeState(ctx, j.TocDocID, &tocFinalizeState)
		return nil
	}

	// Build page pattern context
	j.FinalizePagePatternCtx = buildPagePatternContext(j.Book)

	// Set body range: prefer page pattern analysis, fall back to ToC entries, then full book
	if j.FinalizePagePatternCtx.HasBoundaries {
		j.Book.SetBodyRange(j.FinalizePagePatternCtx.BodyStartPage, j.FinalizePagePatternCtx.BodyEndPage)
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
			j.Book.SetBodyRange(minPage, maxPage)
		} else {
			j.Book.SetBodyRange(1, j.Book.TotalPages)
		}
	}

	// Set phase and persist for crash recovery
	j.Book.SetFinalizePhase(FinalizePhasePattern)
	if err := common.PersistFinalizePhaseSync(ctx, j.TocDocID, FinalizePhasePattern); err != nil {
		if logger != nil {
			logger.Warn("failed to persist finalize phase", "phase", FinalizePhasePattern, "error", err)
		}
	}

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
		logger.Info("pattern analysis context loaded",
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
			logger.Warn("pattern analysis permanently failed, skipping to discover",
				"book_id", j.Book.BookID,
				"retry_count", info.RetryCount,
				"error", result.Error)
		}
		// Mark pattern phase as skipped to prevent re-attempts on restart
		j.Book.SetFinalizePhase(FinalizePhaseDiscover)
		if err := common.PersistFinalizePhaseSync(ctx, j.TocDocID, FinalizePhaseDiscover); err != nil {
			if logger != nil {
				logger.Error("failed to persist pattern phase skip", "error", err)
			}
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

	// Build result locally before storing in BookState
	patternResult := &common.FinalizePatternResult{
		Reasoning: response.Reasoning,
	}

	// Convert patterns
	for _, p := range response.DiscoveredPatterns {
		patternResult.Patterns = append(patternResult.Patterns, common.DiscoveredPattern{
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
		patternResult.Excluded = append(patternResult.Excluded, common.ExcludedRange{
			StartPage: e.StartPage,
			EndPage:   e.EndPage,
			Reason:    e.Reason,
		})
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
	if err := j.persistFinalizePatternResults(ctx); err != nil {
		if logger != nil {
			logger.Error("failed to persist pattern results", "error", err)
		}
		return fmt.Errorf("failed to persist pattern results: %w", err)
	}

	return nil
}

// generateEntriesToFind creates EntryToFind records from discovered patterns.
func (j *Job) generateEntriesToFind(ctx context.Context) {
	if j.Book.GetFinalizePatternResult() == nil {
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
	j.Book.SetEntriesToFind(nil)

	// Generate entries from patterns
	for _, pattern := range j.Book.GetFinalizePatternResult().Patterns {
		identifiers := generateSequence(pattern.RangeStart, pattern.RangeEnd)

		for i, identifier := range identifiers {
			key := strings.ToLower(pattern.LevelName + "_" + identifier)

			if existingIdentifiers[key] {
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

// transitionToFinalizeDiscover moves to the discover phase.
func (j *Job) transitionToFinalizeDiscover(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Set phase and persist for crash recovery
	j.Book.SetFinalizePhase(FinalizePhaseDiscover)
	if err := common.PersistFinalizePhaseSync(ctx, j.TocDocID, FinalizePhaseDiscover); err != nil {
		if logger != nil {
			logger.Warn("failed to persist finalize phase", "phase", FinalizePhaseDiscover, "error", err)
		}
	}

	if logger != nil {
		logger.Info("transitioning to discover phase",
			"book_id", j.Book.BookID,
			"entries_to_find", j.Book.GetEntriesToFindCount())
	}

	if j.Book.GetEntriesToFindCount() == 0 {
		return j.transitionToFinalizeValidate(ctx)
	}

	return j.createFinalizeDiscoverWorkUnits(ctx)
}

// createFinalizeDiscoverWorkUnits creates work units for all entries to discover.
func (j *Job) createFinalizeDiscoverWorkUnits(ctx context.Context) []jobs.WorkUnit {
	var units []jobs.WorkUnit

	for _, entry := range j.Book.GetEntriesToFind() {
		unit := j.createChapterFinderWorkUnit(ctx, entry)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units
}

// createChapterFinderWorkUnit creates a chapter finder agent work unit.
func (j *Job) createChapterFinderWorkUnit(ctx context.Context, entry *common.EntryToFind) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	var excludedRanges []chapter_finder.ExcludedRange
	if j.Book.GetFinalizePatternResult() != nil {
		for _, ex := range j.Book.GetFinalizePatternResult().Excluded {
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

	var ag *agent.Agent

	// Check for saved agent state (job resume case)
	savedState := j.Book.GetAgentState(common.AgentTypeChapterFinder, entry.Key)
	if savedState != nil && !savedState.Complete {
		// Resume existing agent
		if logger != nil {
			logger.Info("resuming chapter finder agent from saved state",
				"agent_id", savedState.AgentID,
				"entry_key", entry.Key,
				"iteration", savedState.Iteration)
		}

		ag = agents.NewChapterFinderAgent(ctx, agents.ChapterFinderConfig{
			Book:           j.Book,
			SystemPrompt:   j.GetPrompt(chapter_finder.PromptKey),
			Entry:          agentEntry,
			ExcludedRanges: excludedRanges,
			Debug:          j.Book.DebugAgents,
			JobID:          j.RecordID,
		})

		if err := ag.RestoreState(&agent.StateExport{
			AgentID:          savedState.AgentID,
			Iteration:        savedState.Iteration,
			Complete:         savedState.Complete,
			MessagesJSON:     savedState.MessagesJSON,
			PendingToolCalls: savedState.PendingToolCalls,
			ToolResults:      savedState.ToolResults,
			ResultJSON:       savedState.ResultJSON,
		}); err != nil {
			if logger != nil {
				logger.Warn("failed to restore chapter finder agent state, starting fresh",
					"entry_key", entry.Key,
					"error", err)
			}
			ag = nil
		}
	}

	// Create fresh agent if not restored
	if ag == nil {
		ag = agents.NewChapterFinderAgent(ctx, agents.ChapterFinderConfig{
			Book:           j.Book,
			SystemPrompt:   j.GetPrompt(chapter_finder.PromptKey),
			Entry:          agentEntry,
			ExcludedRanges: excludedRanges,
			Debug:          j.Book.DebugAgents,
			JobID:          j.RecordID,
		})
	}

	j.FinalizeDiscoverAgents[entry.Key] = ag

	// Persist initial agent state (async, fire-and-forget)
	exported, _ := ag.ExportState()
	initialState := &common.AgentState{
		AgentID:          exported.AgentID,
		AgentType:        common.AgentTypeChapterFinder,
		EntryDocID:       entry.Key,
		Iteration:        exported.Iteration,
		Complete:         false,
		MessagesJSON:     exported.MessagesJSON,
		PendingToolCalls: exported.PendingToolCalls,
		ToolResults:      exported.ToolResults,
		ResultJSON:       "",
	}
	common.PersistAgentStateAsync(ctx, j.Book.BookID, initialState)
	j.Book.SetAgentState(initialState)

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

	ag, ok := j.FinalizeDiscoverAgents[info.FinalizeKey]
	if !ok {
		j.RemoveWorkUnit(result.WorkUnitID)
		j.Book.IncrementFinalizeEntriesComplete()
		// Persist progress immediately after incrementing to ensure crash recovery works
		if err := common.PersistFinalizeProgress(ctx, j.Book); err != nil && logger != nil {
			logger.Warn("failed to persist finalize progress", "error", err)
		}
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
		j.Book.IncrementFinalizeEntriesComplete()
		// Persist progress immediately after incrementing
		if err := common.PersistFinalizeProgress(ctx, j.Book); err != nil && logger != nil {
			logger.Warn("failed to persist finalize progress", "error", err)
		}
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

		// Note: No intermediate state persistence - crash recovery restarts from scratch
		// This eliminates the SendSync bottleneck that serialized agent execution

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

		// Clean up agent state
		j.cleanupFinalizeDiscoverAgentState(ctx, info.FinalizeKey)

		agentResult := ag.Result()
		if agentResult != nil && agentResult.Success {
			if finderResult, ok := agentResult.ToolResult.(*chapter_finder.Result); ok {
				if err := j.saveDiscoveredEntry(ctx, info.FinalizeKey, finderResult); err != nil {
					if logger != nil {
						logger.Warn("failed to save discovered entry", "error", err)
					}
				}
				if finderResult.ScanPage != nil && *finderResult.ScanPage > 0 {
					j.Book.IncrementFinalizeEntriesFound()
				}
			}
		}

		j.Book.IncrementFinalizeEntriesComplete()
		// Persist progress immediately after incrementing counters
		if err := common.PersistFinalizeProgress(ctx, j.Book); err != nil && logger != nil {
			logger.Warn("failed to persist finalize progress", "error", err)
		}
		delete(j.FinalizeDiscoverAgents, info.FinalizeKey)
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	return j.checkFinalizeDiscoverCompletion(ctx), nil
}

// checkFinalizeDiscoverCompletion checks if discover phase is complete.
func (j *Job) checkFinalizeDiscoverCompletion(ctx context.Context) []jobs.WorkUnit {
	entriesComplete, _, _, _ := j.Book.GetFinalizeProgress()
	if entriesComplete >= j.Book.GetEntriesToFindCount() {
		return j.transitionToFinalizeValidate(ctx)
	}
	return nil
}

// transitionToFinalizeValidate moves to the validate phase.
func (j *Job) transitionToFinalizeValidate(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Set phase and persist for crash recovery
	j.Book.SetFinalizePhase(FinalizePhaseValidate)
	if err := common.PersistFinalizePhaseSync(ctx, j.TocDocID, FinalizePhaseValidate); err != nil {
		if logger != nil {
			logger.Warn("failed to persist finalize phase", "phase", FinalizePhaseValidate, "error", err)
		}
	}

	// Find gaps in page coverage
	if err := j.findFinalizeGaps(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to find gaps", "error", err)
		}
	}

	if logger != nil {
		logger.Info("transitioning to validate phase",
			"book_id", j.Book.BookID,
			"gaps", j.Book.GetFinalizeGapsCount())
	}

	if j.Book.GetFinalizeGapsCount() == 0 {
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
	j.Book.SetFinalizeGaps(nil)

	// Check gap from body start to first entry
	if len(sortedEntries) > 0 {
		first := sortedEntries[0]
		if *first.ActualPage-j.Book.GetBodyStart() > MinGapSize {
			j.Book.AppendFinalizeGap(&common.FinalizeGap{
				Key:            fmt.Sprintf("gap_%d_%d", j.Book.GetBodyStart(), *first.ActualPage-1),
				StartPage:      j.Book.GetBodyStart(),
				EndPage:        *first.ActualPage - 1,
				Size:           *first.ActualPage - j.Book.GetBodyStart(),
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

			j.Book.AppendFinalizeGap(&common.FinalizeGap{
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
		if j.Book.GetBodyEnd()-*last.ActualPage > MinGapSize && !j.isPageExcluded(*last.ActualPage+1) {
			j.Book.AppendFinalizeGap(&common.FinalizeGap{
				Key:            fmt.Sprintf("gap_%d_%d", *last.ActualPage+1, j.Book.GetBodyEnd()),
				StartPage:      *last.ActualPage + 1,
				EndPage:        j.Book.GetBodyEnd(),
				Size:           j.Book.GetBodyEnd() - *last.ActualPage,
				PrevEntryTitle: last.Title,
				PrevEntryPage:  *last.ActualPage,
			})
		}
	}

	return nil
}

// isPageExcluded checks if a page is in an excluded range.
func (j *Job) isPageExcluded(page int) bool {
	if j.Book.GetFinalizePatternResult() == nil {
		return false
	}
	for _, ex := range j.Book.GetFinalizePatternResult().Excluded {
		if page >= ex.StartPage && page <= ex.EndPage {
			return true
		}
	}
	return false
}

// createFinalizeGapWorkUnits creates work units for gap investigation.
func (j *Job) createFinalizeGapWorkUnits(ctx context.Context) []jobs.WorkUnit {
	var units []jobs.WorkUnit

	for _, gap := range j.Book.GetFinalizeGaps() {
		unit := j.createGapInvestigatorWorkUnit(ctx, gap)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units
}

// createGapInvestigatorWorkUnit creates a gap investigator agent work unit.
func (j *Job) createGapInvestigatorWorkUnit(ctx context.Context, gap *common.FinalizeGap) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

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

	var ag *agent.Agent

	// Check for saved agent state (job resume case)
	savedState := j.Book.GetAgentState(common.AgentTypeGapInvestigator, gap.Key)
	if savedState != nil && !savedState.Complete {
		// Resume existing agent
		if logger != nil {
			logger.Info("resuming gap investigator agent from saved state",
				"agent_id", savedState.AgentID,
				"gap_key", gap.Key,
				"iteration", savedState.Iteration)
		}

		ag = agents.NewGapInvestigatorAgent(ctx, agents.GapInvestigatorConfig{
			Book:          j.Book,
			SystemPrompt:  j.GetPrompt(gap_investigator.PromptKey),
			Gap:           agentGap,
			LinkedEntries: linkedEntries,
			Debug:         j.Book.DebugAgents,
			JobID:         j.RecordID,
		})

		if err := ag.RestoreState(&agent.StateExport{
			AgentID:          savedState.AgentID,
			Iteration:        savedState.Iteration,
			Complete:         savedState.Complete,
			MessagesJSON:     savedState.MessagesJSON,
			PendingToolCalls: savedState.PendingToolCalls,
			ToolResults:      savedState.ToolResults,
			ResultJSON:       savedState.ResultJSON,
		}); err != nil {
			if logger != nil {
				logger.Warn("failed to restore gap investigator agent state, starting fresh",
					"gap_key", gap.Key,
					"error", err)
			}
			ag = nil
		}
	}

	// Create fresh agent if not restored
	if ag == nil {
		ag = agents.NewGapInvestigatorAgent(ctx, agents.GapInvestigatorConfig{
			Book:          j.Book,
			SystemPrompt:  j.GetPrompt(gap_investigator.PromptKey),
			Gap:           agentGap,
			LinkedEntries: linkedEntries,
			Debug:         j.Book.DebugAgents,
			JobID:         j.RecordID,
		})
	}

	j.FinalizeGapAgents[gap.Key] = ag

	// Persist initial agent state (async, fire-and-forget)
	exported, _ := ag.ExportState()
	initialState := &common.AgentState{
		AgentID:          exported.AgentID,
		AgentType:        common.AgentTypeGapInvestigator,
		EntryDocID:       gap.Key,
		Iteration:        exported.Iteration,
		Complete:         false,
		MessagesJSON:     exported.MessagesJSON,
		PendingToolCalls: exported.PendingToolCalls,
		ToolResults:      exported.ToolResults,
		ResultJSON:       "",
	}
	common.PersistAgentStateAsync(ctx, j.Book.BookID, initialState)
	j.Book.SetAgentState(initialState)

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

	ag, ok := j.FinalizeGapAgents[info.FinalizeKey]
	if !ok {
		j.RemoveWorkUnit(result.WorkUnitID)
		j.Book.IncrementFinalizeGapsComplete()
		// Persist progress immediately after incrementing
		if err := common.PersistFinalizeProgress(ctx, j.Book); err != nil && logger != nil {
			logger.Warn("failed to persist finalize progress", "error", err)
		}
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
		j.Book.IncrementFinalizeGapsComplete()
		// Persist progress immediately after incrementing
		if err := common.PersistFinalizeProgress(ctx, j.Book); err != nil && logger != nil {
			logger.Warn("failed to persist finalize progress", "error", err)
		}
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

		// Note: No intermediate state persistence - crash recovery restarts from scratch
		// This eliminates the SendSync bottleneck that serialized agent execution

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

		// Clean up agent state
		j.cleanupFinalizeGapAgentState(ctx, info.FinalizeKey)

		agentResult := ag.Result()
		if agentResult != nil && agentResult.Success {
			if gapResult, ok := agentResult.ToolResult.(*gap_investigator.Result); ok {
				if err := j.applyGapFix(ctx, info.FinalizeKey, gapResult); err != nil {
					if logger != nil {
						logger.Warn("failed to apply gap fix", "error", err)
					}
				}
				if gapResult.FixType == "add_entry" || gapResult.FixType == "correct_entry" {
					j.Book.IncrementFinalizeGapsFixes()
				}
			}
		}

		j.Book.IncrementFinalizeGapsComplete()
		// Persist progress immediately after incrementing counters
		if err := common.PersistFinalizeProgress(ctx, j.Book); err != nil && logger != nil {
			logger.Warn("failed to persist finalize progress", "error", err)
		}
		delete(j.FinalizeGapAgents, info.FinalizeKey)
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	return j.checkFinalizeValidateCompletion(ctx), nil
}

// checkFinalizeValidateCompletion checks if validate phase is complete.
func (j *Job) checkFinalizeValidateCompletion(ctx context.Context) []jobs.WorkUnit {
	_, _, gapsComplete, _ := j.Book.GetFinalizeProgress()
	if gapsComplete >= j.Book.GetFinalizeGapsCount() {
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

	// Persist finalize phase before marking complete
	j.Book.SetFinalizePhase(FinalizePhaseDone)
	if err := common.PersistFinalizePhaseSync(ctx, j.TocDocID, FinalizePhaseDone); err != nil {
		if logger != nil {
			logger.Warn("failed to persist finalize phase", "error", err)
		}
	}

	j.Book.TocFinalizeComplete()
	// Use sync write for completion to ensure state is persisted before continuing to structure
	tocFinalizeState := j.Book.GetTocFinalizeState()
	if err := common.PersistTocFinalizeStateSync(ctx, j.TocDocID, &tocFinalizeState); err != nil {
		if logger != nil {
			logger.Error("failed to persist finalize completion", "error", err)
		}
		// Roll back in-memory state to match database
		j.Book.TocFinalizeReset()
		j.Book.TocFinalizeStart()
		j.Book.SetFinalizePhase(FinalizePhaseValidate) // Set back to validate phase
		// Don't continue to structure - return nil to let job retry later
		return nil
	}

	if logger != nil {
		_, entriesFound, _, gapsFixes := j.Book.GetFinalizeProgress()
		logger.Info("finalize phase complete",
			"book_id", j.Book.BookID,
			"entries_found", entriesFound,
			"gaps_fixed", gapsFixes)
	}

	// Continue to structure
	return j.MaybeStartStructureInline(ctx)
}

// Helper functions

func buildPagePatternContext(book *common.BookState) *PagePatternContext {
	ctx := &PagePatternContext{}

	par := book.GetPatternAnalysisResult()
	if par != nil {

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

type candidateHeading struct {
	PageNum int
	Text    string
	Level   int
}

func (j *Job) loadChapterStartPages(_ context.Context) ([]types.ChapterStartPage, error) {
	// Derive chapter start pages from pattern analysis ChapterPatterns data.
	// This replaces the old approach of querying is_chapter_start (a label field).
	patternResult := j.Book.GetPatternAnalysisResult()
	if patternResult == nil {
		return nil, nil
	}

	var result []types.ChapterStartPage
	for _, cp := range patternResult.ChapterPatterns {
		result = append(result, types.ChapterStartPage{
			PageNum:       cp.StartPage,
			RunningHeader: cp.RunningHeader,
		})
	}

	sort.Slice(result, func(i, k int) bool {
		return result[i].PageNum < result[k].PageNum
	})

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
	if j.FinalizePagePatternCtx == nil {
		return nil
	}
	return j.FinalizePagePatternCtx.ChapterPatterns
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

	bodyRange := j.Book.GetBodyEnd() - j.Book.GetBodyStart()
	if total > 0 {
		return j.Book.GetBodyStart() + (bodyRange * index / total)
	}
	return j.Book.GetBodyStart() + bodyRange/2
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
	if j.Book.GetFinalizePatternResult() == nil {
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
		Patterns:      j.Book.GetFinalizePatternResult().Patterns,
		Excluded:      j.Book.GetFinalizePatternResult().Excluded,
		EntriesToFind: j.Book.GetEntriesToFind(),
		Reasoning:     j.Book.GetFinalizePatternResult().Reasoning,
	}

	jsonBytes, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("failed to marshal pattern analysis: %w", err)
	}

	// Use sync write for pattern results - this data is critical for restart
	_, err = sink.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      j.Book.BookID,
		Document: map[string]any{
			"pattern_analysis_json": string(jsonBytes),
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return fmt.Errorf("failed to persist pattern results: %w", err)
	}

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
	for _, e := range j.Book.GetEntriesToFind() {
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
			// Use sync write for entry corrections - this is the result of LLM work
			_, err := sink.SendSync(ctx, defra.WriteOp{
				Collection: "TocEntry",
				DocID:      result.EntryDocID,
				Document: map[string]any{
					"actual_page_id": pageDocID,
				},
				Op: defra.OpUpdate,
			})
			if err != nil {
				return fmt.Errorf("failed to correct entry %s: %w", result.EntryDocID, err)
			}
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

	var updatedCount int
	for i, entry := range entries {
		newSortOrder := (i + 1) * 100
		if entry.SortOrder != newSortOrder {
			// Use async write - sort order can be recalculated on crash recovery
			sink.Send(defra.WriteOp{
				Collection: "TocEntry",
				DocID:      entry.DocID,
				Document: map[string]any{
					"sort_order": newSortOrder,
				},
				Op: defra.OpUpdate,
			})
			updatedCount++
		}
	}

	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		logger.Info("re-sorted ToC entries by page",
			"toc_doc_id", j.TocDocID,
			"entry_count", len(entries),
			"updated", updatedCount)
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
	for _, e := range j.Book.GetEntriesToFind() {
		if e.Key == info.FinalizeKey {
			entry = e
			break
		}
	}
	if entry == nil {
		return nil, nil
	}

	delete(j.FinalizeDiscoverAgents, info.FinalizeKey)

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
	for _, g := range j.Book.GetFinalizeGaps() {
		if g.Key == info.FinalizeKey {
			gap = g
			break
		}
	}
	if gap == nil {
		return nil, nil
	}

	delete(j.FinalizeGapAgents, info.FinalizeKey)

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

// --- Finalize Agent State Cleanup ---

// cleanupFinalizeDiscoverAgentState removes chapter finder agent state after completion.
func (j *Job) cleanupFinalizeDiscoverAgentState(ctx context.Context, entryKey string) {
	logger := svcctx.LoggerFrom(ctx)
	existing := j.Book.GetAgentState(common.AgentTypeChapterFinder, entryKey)
	if existing != nil && existing.AgentID != "" {
		// Delete by agent_id since we don't have DocID from async create
		if err := common.DeleteAgentStateByAgentID(ctx, existing.AgentID); err != nil {
			if logger != nil {
				logger.Error("failed to delete agent state from DB, orphaned record remains",
					"agent_id", existing.AgentID,
					"agent_type", common.AgentTypeChapterFinder,
					"entry_key", entryKey,
					"book_id", j.Book.BookID,
					"error", err)
			}
		}
	}
	j.Book.RemoveAgentState(common.AgentTypeChapterFinder, entryKey)
}

// cleanupFinalizeGapAgentState removes gap investigator agent state after completion.
func (j *Job) cleanupFinalizeGapAgentState(ctx context.Context, gapKey string) {
	logger := svcctx.LoggerFrom(ctx)
	existing := j.Book.GetAgentState(common.AgentTypeGapInvestigator, gapKey)
	if existing != nil && existing.AgentID != "" {
		// Delete by agent_id since we don't have DocID from async create
		if err := common.DeleteAgentStateByAgentID(ctx, existing.AgentID); err != nil {
			if logger != nil {
				logger.Error("failed to delete agent state from DB, orphaned record remains",
					"agent_id", existing.AgentID,
					"agent_type", common.AgentTypeGapInvestigator,
					"gap_key", gapKey,
					"book_id", j.Book.BookID,
					"error", err)
			}
		}
	}
	j.Book.RemoveAgentState(common.AgentTypeGapInvestigator, gapKey)
}
