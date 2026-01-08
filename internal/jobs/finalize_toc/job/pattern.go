package job

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/google/uuid"
	pattern_analyzer "github.com/jackzampolin/shelf/internal/agents/pattern_analyzer"
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

	// Build prompts
	systemPrompt := j.GetPrompt(pattern_analyzer.PromptKey)
	userPrompt := pattern_analyzer.BuildUserPrompt(pattern_analyzer.UserPromptData{
		LinkedEntries: j.convertEntriesForPattern(),
		Candidates:    j.convertCandidatesForPattern(candidates),
		BodyStart:     j.Book.BodyStart,
		BodyEnd:       j.Book.BodyEnd,
		TotalPages:    j.Book.TotalPages,
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

	// Build excluded ranges lookup
	isExcluded := func(page int) bool {
		for _, ex := range j.PatternResult.Excluded {
			if page >= ex.StartPage && page <= ex.EndPage {
				return true
			}
		}
		return false
	}

	// Generate entries from patterns
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
			if isExcluded(expectedPage) {
				continue
			}

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

// loadCandidateHeadings loads heading candidates from DefraDB.
func (j *Job) loadCandidateHeadings(ctx context.Context) ([]*CandidateHeading, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, page_num: {_gte: %d, _lte: %d}}) {
			page_num
			headings
		}
	}`, j.Book.BookID, j.Book.BodyStart, j.Book.BodyEnd)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	rawPages, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil, nil
	}

	var candidates []*CandidateHeading
	for _, p := range rawPages {
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}

		pageNum := 0
		if pn, ok := page["page_num"].(float64); ok {
			pageNum = int(pn)
		}

		// headings is a JSON field - may come as []any or as a JSON string
		var headings []any
		switch h := page["headings"].(type) {
		case []any:
			headings = h
		case string:
			// Parse JSON string
			if err := json.Unmarshal([]byte(h), &headings); err != nil {
				continue
			}
		default:
			continue
		}

		for _, h := range headings {
			heading, ok := h.(map[string]any)
			if !ok {
				continue
			}

			text, _ := heading["text"].(string)
			level := 0
			if lv, ok := heading["level"].(float64); ok {
				level = int(lv)
			}

			if text != "" {
				candidates = append(candidates, &CandidateHeading{
					PageNum: pageNum,
					Text:    text,
					Level:   level,
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
