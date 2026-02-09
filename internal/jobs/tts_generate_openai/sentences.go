package tts_generate_openai

import (
	"strings"
	"unicode"
)

const maxOpenAITTSChars = 4096

var commonAbbreviations = map[string]struct{}{
	"mr": {}, "mrs": {}, "ms": {}, "dr": {}, "prof": {}, "sr": {}, "jr": {},
	"st": {}, "mt": {}, "vs": {}, "etc": {}, "no": {}, "vol": {}, "rev": {},
	"fig": {}, "al": {}, "inc": {}, "ltd": {}, "co": {}, "dept": {}, "est": {},
	"jan": {}, "feb": {}, "mar": {}, "apr": {}, "jun": {}, "jul": {}, "aug": {},
	"sep": {}, "sept": {}, "oct": {}, "nov": {}, "dec": {},
	"a.m": {}, "p.m": {}, "e.g": {}, "i.e": {}, "u.s": {}, "u.k": {},
}

// splitIntoSentences splits text into sentence-like chunks and enforces OpenAI's
// 4096-character input limit with clause-level fallback splits.
func splitIntoSentences(text string) []string {
	text = normalizeText(text)
	if text == "" {
		return nil
	}

	var segments []string
	start := 0

	for i := 0; i < len(text); i++ {
		ch := text[i]
		if !isSentencePunctuation(ch) {
			continue
		}
		if ch == '.' && shouldSkipPeriodSplit(text, i) {
			continue
		}
		if !isBoundary(text, i) {
			continue
		}

		chunk := strings.TrimSpace(text[start : i+1])
		if chunk != "" {
			segments = append(segments, splitLongSegment(chunk, maxOpenAITTSChars)...)
		}
		start = i + 1
	}

	tail := strings.TrimSpace(text[start:])
	if tail != "" {
		segments = append(segments, splitLongSegment(tail, maxOpenAITTSChars)...)
	}

	return segments
}

func normalizeText(text string) string {
	text = strings.ReplaceAll(text, "\r\n", "\n")
	text = strings.ReplaceAll(text, "\r", "\n")
	// Collapse whitespace/newlines so sentence scanning has stable boundaries.
	return strings.Join(strings.Fields(text), " ")
}

func isSentencePunctuation(ch byte) bool {
	return ch == '.' || ch == '!' || ch == '?'
}

func shouldSkipPeriodSplit(text string, idx int) bool {
	// Ellipsis
	if (idx > 0 && text[idx-1] == '.') || (idx+1 < len(text) && text[idx+1] == '.') {
		return true
	}

	// Decimal numbers
	if idx > 0 && idx+1 < len(text) && isDigit(text[idx-1]) && isDigit(text[idx+1]) {
		return true
	}

	token := tokenBeforePeriod(text, idx)
	if token == "" {
		return false
	}

	// Initials and single-letter abbreviations (e.g., "A.")
	if len(token) == 1 && isAlpha(token[0]) {
		return true
	}

	// Known abbreviations
	if _, ok := commonAbbreviations[strings.ToLower(token)]; ok {
		return true
	}

	return false
}

func tokenBeforePeriod(text string, idx int) string {
	i := idx - 1
	for i >= 0 && !isTokenBoundary(text[i]) {
		i--
	}
	return text[i+1 : idx]
}

func isBoundary(text string, punctIdx int) bool {
	i := punctIdx + 1
	for i < len(text) && isClosingPunctuation(text[i]) {
		i++
	}
	if i >= len(text) {
		return true
	}
	if !isSpace(text[i]) {
		return false
	}
	for i < len(text) && isSpace(text[i]) {
		i++
	}
	if i >= len(text) {
		return true
	}

	return isLikelySentenceStart(text, i)
}

func isLikelySentenceStart(text string, idx int) bool {
	if idx >= len(text) {
		return false
	}
	r := rune(text[idx])
	if unicode.IsUpper(r) || unicode.IsDigit(r) {
		return true
	}
	if isOpeningQuoteOrBracket(text[idx]) {
		j := idx + 1
		for j < len(text) && isOpeningQuoteOrBracket(text[j]) {
			j++
		}
		if j < len(text) {
			rr := rune(text[j])
			return unicode.IsUpper(rr) || unicode.IsDigit(rr)
		}
	}
	return false
}

func splitLongSegment(segment string, maxChars int) []string {
	segment = strings.TrimSpace(segment)
	if segment == "" {
		return nil
	}
	runes := []rune(segment)
	if len(runes) <= maxChars {
		return []string{segment}
	}

	var out []string
	start := 0
	for start < len(runes) {
		remaining := len(runes) - start
		if remaining <= maxChars {
			part := strings.TrimSpace(string(runes[start:]))
			if part != "" {
				out = append(out, part)
			}
			break
		}

		cut := start + maxChars
		if boundary := findClauseBoundary(runes, start+maxChars/2, cut); boundary > start {
			cut = boundary + 1
		} else if boundary := findClauseBoundaryForward(runes, cut, min(start+maxChars+maxChars/4, len(runes))); boundary > start {
			cut = boundary + 1
		}

		part := strings.TrimSpace(string(runes[start:cut]))
		if part != "" {
			out = append(out, part)
		}
		start = cut
	}
	return out
}

func findClauseBoundary(runes []rune, from, to int) int {
	if to > len(runes) {
		to = len(runes)
	}
	for i := to - 1; i >= from && i >= 0; i-- {
		if isClauseBoundaryRune(runes[i]) {
			return i
		}
	}
	return -1
}

func findClauseBoundaryForward(runes []rune, from, to int) int {
	if from < 0 {
		from = 0
	}
	if to > len(runes) {
		to = len(runes)
	}
	for i := from; i < to; i++ {
		if isClauseBoundaryRune(runes[i]) {
			return i
		}
	}
	return -1
}

func isClauseBoundaryRune(r rune) bool {
	switch r {
	case ',', ';', ':', '—', '-':
		return true
	default:
		return false
	}
}

func isTokenBoundary(ch byte) bool {
	return isSpace(ch) || ch == '"' || ch == '\'' || ch == '(' || ch == ')' || ch == '[' || ch == ']' || ch == '{' || ch == '}'
}

func isSpace(ch byte) bool {
	return ch == ' ' || ch == '\n' || ch == '\t'
}

func isDigit(ch byte) bool {
	return ch >= '0' && ch <= '9'
}

func isAlpha(ch byte) bool {
	return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z')
}

func isClosingPunctuation(ch byte) bool {
	switch ch {
	case '"', '\'', ')', ']', '}':
		return true
	default:
		return false
	}
}

func isOpeningQuoteOrBracket(ch byte) bool {
	switch ch {
	case '"', '\'', '(', '[', '{':
		return true
	default:
		return false
	}
}
