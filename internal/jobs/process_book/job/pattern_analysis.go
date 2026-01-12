package job

import (
	"context"
	"encoding/json"
	"fmt"

	page_pattern_analyzer "github.com/jackzampolin/shelf/internal/agents/page_pattern_analyzer"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// PatternAnalysisSubtype identifies which of the 3 pattern analysis calls a work unit represents.
type PatternAnalysisSubtype string

const (
	PatternAnalysisPageNumbers PatternAnalysisSubtype = "page_numbers"
	PatternAnalysisChapters    PatternAnalysisSubtype = "chapters"
	PatternAnalysisBoundaries  PatternAnalysisSubtype = "boundaries"
)

// CreatePatternAnalysisWorkUnits creates the initial pattern analysis work units.
// This is a 3-phase sequential process:
//   Phase 1: Returns 2 parallel work units (page_numbers and chapters)
//   Phase 2: After both complete, maybeCreateBoundariesWorkUnit creates the boundaries unit
//   Phase 3: handleBodyBoundariesComplete aggregates all results and persists to DefraDB
// Only returns the Phase 1 units. Phases 2-3 are triggered via completion handlers.
func (j *Job) CreatePatternAnalysisWorkUnits(ctx context.Context) []jobs.WorkUnit {
	var units []jobs.WorkUnit

	// Create page number pattern detection work unit
	if unit, unitID := common.CreatePageNumberPatternWorkUnit(ctx, j); unit != nil {
		j.RegisterWorkUnit(unitID, WorkUnitInfo{
			UnitType:               WorkUnitTypePatternAnalysis,
			PatternAnalysisSubtype: string(PatternAnalysisPageNumbers),
		})
		units = append(units, *unit)
	}

	// Create chapter pattern detection work unit
	if unit, unitID := common.CreateChapterPatternsWorkUnit(ctx, j); unit != nil {
		j.RegisterWorkUnit(unitID, WorkUnitInfo{
			UnitType:               WorkUnitTypePatternAnalysis,
			PatternAnalysisSubtype: string(PatternAnalysisChapters),
		})
		units = append(units, *unit)
	}

	return units
}

// HandlePatternAnalysisComplete processes pattern analysis work unit completion.
func (j *Job) HandlePatternAnalysisComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	if result.ChatResult == nil || result.ChatResult.ParsedJSON == nil {
		return nil, fmt.Errorf("pattern analysis returned no result")
	}

	subtype := PatternAnalysisSubtype(info.PatternAnalysisSubtype)

	switch subtype {
	case PatternAnalysisPageNumbers:
		return j.handlePageNumberPatternComplete(ctx, result)

	case PatternAnalysisChapters:
		return j.handleChapterPatternsComplete(ctx, result)

	case PatternAnalysisBoundaries:
		return j.handleBodyBoundariesComplete(ctx, result)

	default:
		return nil, fmt.Errorf("unknown pattern analysis subtype: %s", subtype)
	}
}

// handlePageNumberPatternComplete processes page number pattern detection completion.
func (j *Job) handlePageNumberPatternComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	// Parse the result
	parsedJSON := result.ChatResult.ParsedJSON
	jsonBytes, err := json.Marshal(parsedJSON)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal page number pattern result: %w", err)
	}

	var wrapper struct {
		PageNumberPattern *page_pattern_analyzer.PageNumberPattern `json:"page_number_pattern"`
	}
	if err := json.Unmarshal(jsonBytes, &wrapper); err != nil {
		return nil, fmt.Errorf("failed to parse page number pattern result: %w", err)
	}

	// Store result in book state (thread-safe)
	j.Book.SetPageNumberPattern(wrapper.PageNumberPattern)

	// Check if we can create boundaries work unit
	return j.maybeCreateBoundariesWorkUnit(ctx), nil
}

// handleChapterPatternsComplete processes chapter pattern detection completion.
func (j *Job) handleChapterPatternsComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	// Parse the result
	parsedJSON := result.ChatResult.ParsedJSON
	jsonBytes, err := json.Marshal(parsedJSON)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal chapter patterns result: %w", err)
	}

	var wrapper struct {
		ChapterPatterns []page_pattern_analyzer.ChapterPattern `json:"chapter_patterns"`
	}
	if err := json.Unmarshal(jsonBytes, &wrapper); err != nil {
		return nil, fmt.Errorf("failed to parse chapter patterns result: %w", err)
	}

	// Store result in book state (thread-safe)
	j.Book.SetChapterPatterns(wrapper.ChapterPatterns)

	// Check if we can create boundaries work unit
	return j.maybeCreateBoundariesWorkUnit(ctx), nil
}

// handleBodyBoundariesComplete processes body boundary detection completion.
func (j *Job) handleBodyBoundariesComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	// Parse the result
	parsedJSON := result.ChatResult.ParsedJSON
	jsonBytes, err := json.Marshal(parsedJSON)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal body boundaries result: %w", err)
	}

	var wrapper struct {
		BodyBoundaries *page_pattern_analyzer.BodyBoundaries `json:"body_boundaries"`
	}
	if err := json.Unmarshal(jsonBytes, &wrapper); err != nil {
		return nil, fmt.Errorf("failed to parse body boundaries result: %w", err)
	}

	// Aggregate all pattern analysis results (thread-safe access)
	aggregatedResult := &page_pattern_analyzer.Result{
		PageNumberPattern: j.Book.GetPageNumberPattern(),
		BodyBoundaries:    wrapper.BodyBoundaries,
		ChapterPatterns:   j.Book.GetChapterPatterns(),
		Reasoning:         "Pattern analysis complete",
	}

	// Save to database
	if err := common.SavePatternAnalysisResult(ctx, j.Book.BookDocID, aggregatedResult); err != nil {
		return nil, fmt.Errorf("failed to save pattern analysis result: %w", err)
	}

	// Store in book state
	j.Book.PatternAnalysisResult = aggregatedResult

	// Mark pattern analysis as complete
	j.Book.PatternAnalysis.Complete()

	// Persist completion state to DefraDB
	if err := j.PersistPatternAnalysisState(ctx); err != nil {
		return nil, fmt.Errorf("failed to persist pattern analysis state: %w", err)
	}

	return nil, nil
}

// maybeCreateBoundariesWorkUnit creates the boundaries work unit if both prerequisites are complete.
func (j *Job) maybeCreateBoundariesWorkUnit(ctx context.Context) []jobs.WorkUnit {
	// Check if both page numbers and chapters are available (thread-safe access)
	pageNumberPattern := j.Book.GetPageNumberPattern()
	chapterPatterns := j.Book.GetChapterPatterns()

	if pageNumberPattern == nil || chapterPatterns == nil {
		return nil
	}

	// Create boundaries work unit
	unit, unitID := common.CreateBodyBoundariesWorkUnit(
		ctx,
		j,
		pageNumberPattern,
		chapterPatterns,
	)

	if unit != nil {
		j.RegisterWorkUnit(unitID, WorkUnitInfo{
			UnitType:               WorkUnitTypePatternAnalysis,
			PatternAnalysisSubtype: string(PatternAnalysisBoundaries),
		})
		return []jobs.WorkUnit{*unit}
	}

	return nil
}
