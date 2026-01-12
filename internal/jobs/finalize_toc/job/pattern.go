package job

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/google/uuid"
	pattern_analyzer "github.com/jackzampolin/shelf/internal/agents/pattern_analyzer"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreatePatternWorkUnit creates a work unit for pattern analysis.
func (j *Job) CreatePatternWorkUnit(ctx context.Context) (*jobs.WorkUnit, error) {
	// Load candidate headings from Page.headings
	candidates, err := j.loadCandidateHeadings(ctx)
	if err != nil {
		// Non-fatal - proceed without candidates
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Info("failed to load candidate headings", "error", err)
		}
	}

	// Load chapter start pages from labels (pages with is_chapter_start=true)
	chapterStartPages, err := j.loadChapterStartPages(ctx)
	if err != nil {
		// Non-fatal - proceed without chapter start pages
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Info("failed to load chapter start pages", "error", err)
		}
	}

	// Log candidate count for debugging
	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		logger.Info("pattern analysis context loaded",
			"candidate_count", len(candidates),
			"detected_chapters", len(j.PagePatternCtx.ChapterPatterns),
			"chapter_start_pages", len(chapterStartPages),
			"body_start", j.Book.BodyStart,
			"body_end", j.Book.BodyEnd,
			"linked_entries", len(j.LinkedEntries))
	}

	// Build prompts with enhanced context
	systemPrompt := j.GetPrompt(pattern_analyzer.PromptKey)
	userPrompt := pattern_analyzer.BuildUserPrompt(pattern_analyzer.UserPromptData{
		LinkedEntries:     j.convertEntriesForPattern(),
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
		Model: "", // Will be set by scheduler
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
		UnitType: WorkUnitTypePattern,
		Phase:    PhasePattern,
	})

	return unit, nil
}

// ProcessPatternResult parses and stores pattern analysis results.
func (j *Job) ProcessPatternResult(ctx context.Context, result jobs.WorkResult) error {
	if result.ChatResult == nil {
		return fmt.Errorf("no chat result")
	}

	// Parse JSON response (use ParsedJSON if available, otherwise Content)
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

	// Convert to job types
	j.PatternResult = &PatternResult{
		Reasoning: response.Reasoning,
	}

	// Convert patterns
	for _, p := range response.DiscoveredPatterns {
		j.PatternResult.Patterns = append(j.PatternResult.Patterns, DiscoveredPattern{
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
		j.PatternResult.Excluded = append(j.PatternResult.Excluded, ExcludedRange{
			StartPage: e.StartPage,
			EndPage:   e.EndPage,
			Reason:    e.Reason,
		})
	}

	// Generate entries to find from discovered patterns
	j.generateEntriesToFind()

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("pattern analysis complete",
			"patterns_found", len(j.PatternResult.Patterns),
			"excluded_ranges", len(j.PatternResult.Excluded),
			"entries_to_find", len(j.EntriesToFind))
	}

	// Persist pattern results to Book
	if err := j.PersistPatternResults(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to persist pattern results", "error", err)
		}
	}

	return nil
}

// PatternAnalysisData is the structure persisted to Book.pattern_analysis_json.
type PatternAnalysisData struct {
	Patterns      []DiscoveredPattern `json:"patterns"`
	Excluded      []ExcludedRange     `json:"excluded_ranges"`
	EntriesToFind []*EntryToFind      `json:"entries_to_find"`
	Reasoning     string              `json:"reasoning"`
}

// PersistPatternResults persists pattern analysis results to the Book record.
func (j *Job) PersistPatternResults(ctx context.Context) error {
	if j.PatternResult == nil {
		return nil
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Build the pattern analysis data structure
	data := PatternAnalysisData{
		Patterns:      j.PatternResult.Patterns,
		Excluded:      j.PatternResult.Excluded,
		EntriesToFind: j.EntriesToFind,
		Reasoning:     j.PatternResult.Reasoning,
	}

	// Serialize to JSON
	jsonBytes, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("failed to marshal pattern analysis: %w", err)
	}

	// Update Book with pattern analysis
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

// generateEntriesToFind creates EntryToFind records from discovered patterns.
func (j *Job) generateEntriesToFind() {
	if j.PatternResult == nil {
		return
	}

	// Build a set of existing entry identifiers
	existingIdentifiers := make(map[string]bool)
	for _, entry := range j.LinkedEntries {
		if entry.LevelName != "" && entry.EntryNumber != "" {
			key := strings.ToLower(entry.LevelName + "_" + entry.EntryNumber)
			existingIdentifiers[key] = true
		}
	}

	// Generate entries from patterns
	// Note: excluded ranges are passed to the chapter finder agent to constrain search,
	// NOT used here to filter entries. The estimated page might be wrong, so we should
	// still search for all chapters in the pattern range.
	for _, pattern := range j.PatternResult.Patterns {
		// Generate sequence from RangeStart to RangeEnd
		identifiers := generateSequence(pattern.RangeStart, pattern.RangeEnd)

		for i, identifier := range identifiers {
			key := strings.ToLower(pattern.LevelName + "_" + identifier)

			// Skip if already exists
			if existingIdentifiers[key] {
				continue
			}

			// Estimate page location based on sequence position
			expectedPage := j.estimatePageLocation(pattern, identifier, i, len(identifiers))

			// Calculate search range
			searchStart := expectedPage - 20
			if searchStart < j.Book.BodyStart {
				searchStart = j.Book.BodyStart
			}
			searchEnd := expectedPage + 20
			if searchEnd > j.Book.BodyEnd {
				searchEnd = j.Book.BodyEnd
			}

			j.EntriesToFind = append(j.EntriesToFind, &EntryToFind{
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

// estimatePageLocation estimates where an entry should be based on sequence.
func (j *Job) estimatePageLocation(pattern DiscoveredPattern, identifier string, index, total int) int {
	// Find surrounding linked entries for this pattern type
	var beforePage, afterPage int
	beforeFound, afterFound := false, false

	for _, entry := range j.LinkedEntries {
		if entry.ActualPage == nil || entry.LevelName != pattern.LevelName {
			continue
		}

		// Compare entry number to our identifier
		cmp := compareIdentifiers(entry.EntryNumber, identifier)
		if cmp < 0 && *entry.ActualPage > beforePage {
			beforePage = *entry.ActualPage
			beforeFound = true
		} else if cmp > 0 && (!afterFound || *entry.ActualPage < afterPage) {
			afterPage = *entry.ActualPage
			afterFound = true
		}
	}

	// Interpolate position
	if beforeFound && afterFound {
		// Linear interpolation between known entries
		return beforePage + (afterPage-beforePage)/2
	} else if beforeFound {
		// Add some pages after the previous entry
		return beforePage + 10
	} else if afterFound {
		// Some pages before the next entry
		return afterPage - 10
	}

	// Fallback: estimate based on position in sequence
	bodyRange := j.Book.BodyEnd - j.Book.BodyStart
	if total > 0 {
		return j.Book.BodyStart + (bodyRange * index / total)
	}
	return j.Book.BodyStart + bodyRange/2
}

// compareIdentifiers compares two entry identifiers (handles numbers and roman numerals).
func compareIdentifiers(a, b string) int {
	// Try numeric comparison
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

	// Try roman numeral comparison
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

	// Fallback to string comparison
	return strings.Compare(strings.ToLower(a), strings.ToLower(b))
}

// generateSequence generates a sequence of identifiers from start to end.
func generateSequence(start, end string) []string {
	// Try numeric
	startNum, startErr := strconv.Atoi(start)
	endNum, endErr := strconv.Atoi(end)
	if startErr == nil && endErr == nil {
		var result []string
		for i := startNum; i <= endNum; i++ {
			result = append(result, strconv.Itoa(i))
		}
		return result
	}

	// Try roman numerals
	startRoman := romanToInt(strings.ToUpper(start))
	endRoman := romanToInt(strings.ToUpper(end))
	if startRoman > 0 && endRoman > 0 {
		var result []string
		for i := startRoman; i <= endRoman; i++ {
			result = append(result, intToRoman(i))
		}
		return result
	}

	// Fallback to single item
	return []string{start}
}

// romanToInt converts a roman numeral to integer.
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

// intToRoman converts an integer to roman numeral.
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

// loadCandidateHeadings loads heading candidates from the in-memory BookState.
// Headings are extracted during the blend phase and cached in PageState.
func (j *Job) loadCandidateHeadings(ctx context.Context) ([]*CandidateHeading, error) {
	var candidates []*CandidateHeading

	// Iterate through pages in the body range
	for pageNum := j.Book.BodyStart; pageNum <= j.Book.BodyEnd; pageNum++ {
		pageState := j.Book.GetPage(pageNum)
		if pageState == nil {
			continue
		}

		headings := pageState.GetHeadings()
		for _, h := range headings {
			if h.Text != "" {
				candidates = append(candidates, &CandidateHeading{
					PageNum: pageNum,
					Text:    h.Text,
					Level:   h.Level,
				})
			}
		}
	}

	return candidates, nil
}

// convertEntriesForPattern converts linked entries for pattern analyzer input.
func (j *Job) convertEntriesForPattern() []pattern_analyzer.LinkedEntry {
	var result []pattern_analyzer.LinkedEntry
	for _, e := range j.LinkedEntries {
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

// convertCandidatesForPattern converts candidates for pattern analyzer input.
func (j *Job) convertCandidatesForPattern(candidates []*CandidateHeading) []pattern_analyzer.CandidateHeading {
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

// convertDetectedChapters converts PagePatternCtx.ChapterPatterns to pattern analyzer format.
func (j *Job) convertDetectedChapters() []pattern_analyzer.DetectedChapter {
	if j.PagePatternCtx == nil {
		return nil
	}
	var result []pattern_analyzer.DetectedChapter
	for _, dc := range j.PagePatternCtx.ChapterPatterns {
		result = append(result, pattern_analyzer.DetectedChapter{
			PageNum:       dc.PageNum,
			RunningHeader: dc.RunningHeader,
			ChapterTitle:  dc.ChapterTitle,
			ChapterNumber: dc.ChapterNumber,
			Confidence:    dc.Confidence,
		})
	}
	return result
}

// loadChapterStartPages queries pages with is_chapter_start=true from DefraDB.
func (j *Job) loadChapterStartPages(ctx context.Context) ([]pattern_analyzer.ChapterStartPage, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	// Query pages with is_chapter_start=true for this book
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

	var result []pattern_analyzer.ChapterStartPage
	for _, p := range rawPages {
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}

		csp := pattern_analyzer.ChapterStartPage{}
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
