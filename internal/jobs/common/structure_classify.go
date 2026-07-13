package common

import (
	"fmt"
	"strings"
	"unicode"
)

// PageText holds text from a single page.
type PageText struct {
	ScanPage    int
	PrintedPage *string
	RawText     string
	CleanedText string
}

// TextEdit represents an edit from LLM polish.
type TextEdit struct {
	OldText string `json:"old_text"`
	NewText string `json:"new_text"`
	Reason  string `json:"reason"`
}

// ClassifyResult represents the LLM classification response.
type ClassifyResult struct {
	Classifications map[string]string `json:"classifications"`
	ContentTypes    map[string]string `json:"content_types"`
	AudioInclude    map[string]bool   `json:"audio_include"`
	Reasoning       map[string]string `json:"reasoning"`
}

// PolishResult represents the LLM polish response.
type PolishResult struct {
	Edits []TextEdit `json:"edits"`
}

// BuildClassifyPrompt builds the user prompt for content classification.
func BuildClassifyPrompt(chapters []*ChapterState, totalPages int) string {
	var lines []string
	lines = append(lines, fmt.Sprintf("Total pages in book: %d", totalPages))
	lines = append(lines, "Classify each entry with content_type, matter_type, and audio_include:\n")

	for i, ch := range chapters {
		wordCount := ch.WordCount
		if wordCount == 0 && ch.MechanicalText != "" {
			wordCount = CountWords(ch.MechanicalText)
		}
		snippet := buildClassifySnippet(ch.MechanicalText)
		signals := classifyContentSignals(ch.MechanicalText, ch.Title)

		pageRange := fmt.Sprintf("pages %d-%d", ch.StartPage, ch.EndPage)
		if ch.EndPage == 0 || ch.EndPage == ch.StartPage {
			pageRange = fmt.Sprintf("page %d", ch.StartPage)
		}

		line := fmt.Sprintf(
			"%d. \"%s\" (%s, level %d %s, word_count %d) [id: %s]\n   content_signals: %s\n   text: %s",
			i+1, ch.Title, pageRange, ch.Level, ch.LevelName, wordCount, ch.EntryID, signals, snippet,
		)
		lines = append(lines, line)
	}

	lines = append(lines, "\nReturn JSON with classifications, content_types, audio_include, and reasoning for each entry.")
	return strings.Join(lines, "\n")
}

func buildClassifySnippet(text string) string {
	text = strings.TrimSpace(text)
	if text == "" {
		return "[no text]"
	}

	var parts []string
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		parts = append(parts, line)
		if len(strings.Join(parts, " | ")) >= maxClassifySnippetChars {
			break
		}
	}
	if len(parts) == 0 {
		return "[no text]"
	}

	snippet := strings.Join(parts, " | ")
	if len(snippet) > maxClassifySnippetChars {
		snippet = snippet[:maxClassifySnippetChars] + "..."
	}
	return snippet
}

func classifyContentSignals(text, title string) string {
	var signals []string
	lower := strings.ToLower(title + "\n" + text)
	for _, keyword := range []string{
		"order of battle",
		"roster",
		"bibliography",
		"glossary",
		"index",
		"abbreviations",
		"chronology",
		"table",
	} {
		if strings.Contains(lower, keyword) {
			signals = append(signals, "keyword:"+keyword)
		}
	}

	var nonEmpty, shortLines, listLike, tableLike int
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		nonEmpty++
		if len(line) <= 48 {
			shortLines++
		}
		if strings.HasPrefix(line, "-") || strings.HasPrefix(line, "*") || looksNumberedListLine(line) {
			listLike++
		}
		if strings.Count(line, "|") >= 2 || strings.Count(line, "\t") >= 2 {
			tableLike++
		}
	}

	if nonEmpty > 0 {
		if shortLines*2 >= nonEmpty {
			signals = append(signals, fmt.Sprintf("many_short_lines:%d/%d", shortLines, nonEmpty))
		}
		if listLike*4 >= nonEmpty {
			signals = append(signals, fmt.Sprintf("list_like_lines:%d/%d", listLike, nonEmpty))
		}
		if tableLike > 0 {
			signals = append(signals, fmt.Sprintf("table_like_lines:%d/%d", tableLike, nonEmpty))
		}
	}

	if len(signals) == 0 {
		return "none"
	}
	return strings.Join(signals, ", ")
}

func looksNumberedListLine(line string) bool {
	if line == "" || !unicode.IsDigit(rune(line[0])) {
		return false
	}
	for _, r := range line[1:] {
		switch {
		case unicode.IsDigit(r):
			continue
		case r == '.' || r == ')' || r == ':':
			return true
		case unicode.IsSpace(r):
			continue
		default:
			return false
		}
	}
	return false
}
