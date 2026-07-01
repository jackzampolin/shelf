package job

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"unicode"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// loadExistingPatternResults checks the DB for pattern_analysis_json from a previous
// finalize attempt. If found, loads it into BookState and returns true.
// This allows crash recovery to skip the pattern analysis LLM call.
func (j *Job) loadExistingPatternResults(ctx context.Context) bool {
	logger := svcctx.LoggerFrom(ctx)

	if err := defra.ValidateID(j.Book.BookID); err != nil {
		if logger != nil {
			logger.Error("loadExistingPatternResults invalid book ID", "book_id", j.Book.BookID, "error", err)
		}
		return false
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return false
	}

	query := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			pattern_analysis_json
		}
	}`, j.Book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		if logger != nil {
			logger.Error("loadExistingPatternResults query failed", "book_id", j.Book.BookID, "error", err)
		}
		return false
	}

	books, ok := resp.Data["Book"].([]any)
	if !ok || len(books) == 0 {
		return false
	}

	bookData, ok := books[0].(map[string]any)
	if !ok {
		return false
	}

	paJSON, ok := bookData["pattern_analysis_json"].(string)
	if !ok || paJSON == "" {
		return false
	}

	var data struct {
		Patterns      []common.DiscoveredPattern `json:"patterns"`
		Excluded      []common.ExcludedRange     `json:"excluded_ranges"`
		EntriesToFind []*common.EntryToFind      `json:"entries_to_find"`
		Reasoning     string                     `json:"reasoning"`
	}
	if err := json.Unmarshal([]byte(paJSON), &data); err != nil {
		if logger != nil {
			logger.Error("loadExistingPatternResults failed to parse pattern_analysis_json", "book_id", j.Book.BookID, "error", err)
		}
		return false
	}

	j.Book.SetFinalizePatternResult(&common.FinalizePatternResult{
		Patterns:  data.Patterns,
		Excluded:  data.Excluded,
		Reasoning: data.Reasoning,
	})
	j.Book.SetEntriesToFind(data.EntriesToFind)

	if logger != nil {
		logger.Debug("loadExistingPatternResults reusing saved pattern analysis",
			"book_id", j.Book.BookID,
			"patterns", len(data.Patterns),
			"entries_to_find", len(data.EntriesToFind))
	}

	return true
}

// Helper functions

func buildPagePatternContext(_ *common.BookState) *PagePatternContext {
	// Early pattern analysis has been removed - return empty context.
	// Body boundaries will be derived from ToC entries in StartFinalizePhase.
	return &PagePatternContext{}
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

func (j *Job) applyGapFix(ctx context.Context, gapKey string, result *gap_investigator.Result) (defra.WriteResult, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return defra.WriteResult{}, fmt.Errorf("defra client not in context")
	}

	switch result.FixType {
	case "add_entry":
		if result.ScanPage == 0 {
			return defra.WriteResult{}, nil
		}

		pageDocID := j.getPageDocID(result.ScanPage)
		sortOrder := result.ScanPage * 1000
		uniqueKey := fmt.Sprintf("%s:validated:%s", j.TocDocID, gapKey)

		entryData := map[string]any{
			"_tocID":     j.TocDocID,
			"unique_key": uniqueKey,
			"title":      result.Title,
			"level":      result.Level,
			"level_name": result.LevelName,
			"sort_order": sortOrder,
			"source":     "validated",
		}

		if pageDocID != "" {
			entryData["_actual_pageID"] = pageDocID
		}

		filter := map[string]any{
			"unique_key": map[string]any{"_eq": uniqueKey},
		}

		writeResult, err := defraClient.UpsertWithVersion(ctx, "TocEntry", filter, entryData, entryData)
		if err != nil {
			return defra.WriteResult{}, fmt.Errorf("failed to upsert validated entry: %w", err)
		}
		j.Book.TrackWrite("TocEntry", writeResult.DocID, writeResult.CID)
		return writeResult, nil

	case "correct_entry":
		if result.EntryDocID == "" || result.ScanPage == 0 {
			return defra.WriteResult{}, nil
		}

		pageDocID := j.getPageDocID(result.ScanPage)
		if pageDocID != "" {
			// Use sync write for entry corrections - this is the result of LLM work
			writeResult, err := common.SendTracked(ctx, j.Book, defra.WriteOp{
				Collection: "TocEntry",
				DocID:      result.EntryDocID,
				Document: map[string]any{
					"_actual_pageID": pageDocID,
				},
				Op: defra.OpUpdate,
			})
			if err != nil {
				return defra.WriteResult{}, fmt.Errorf("failed to correct entry %s: %w", result.EntryDocID, err)
			}
			return writeResult, nil
		}

	case "flag_for_review":
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Debug("gap flagged for review",
				"gap_key", gapKey,
				"reasoning", result.Reasoning)
		}

	case "no_fix_needed":
		// Nothing to do
	}

	return defra.WriteResult{}, nil
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
