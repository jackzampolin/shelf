package tools

import (
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

var (
	htmlTagRe             = regexp.MustCompile(`(?s)<[^>]+>`)
	markdownHeadingLineRe = regexp.MustCompile(`(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$`)
	positiveIntRe         = regexp.MustCompile(`\b\d{1,4}\b`)
)

func printedPageNumberFromHeaders(headers []string) int {
	for _, header := range headers {
		if n, ok := firstPositiveInt(header); ok {
			return n
		}
	}
	return 0
}

func sectionHeaderMatchesTitlePrefix(headers []string, title, entryNumber string) bool {
	targetWords := strings.Fields(normalizeForEvidence(title))
	if len(targetWords) < 3 {
		return false
	}
	for _, header := range headers {
		headerWords := strings.Fields(stripEntryNumberPrefixForEvidence(header, entryNumber))
		if len(headerWords) < 3 || len(headerWords) > len(targetWords) {
			continue
		}
		if strings.Join(headerWords, " ") == strings.Join(targetWords[:len(headerWords)], " ") {
			return true
		}
	}
	return false
}

func stripEntryNumberPrefixForEvidence(header, entryNumber string) string {
	normalizedHeader := normalizeForEvidence(header)
	normalizedEntry := normalizeForEvidence(entryNumber)
	if normalizedEntry == "" {
		return normalizedHeader
	}
	if normalizedHeader == normalizedEntry {
		return ""
	}
	return strings.TrimSpace(strings.TrimPrefix(normalizedHeader, normalizedEntry+" "))
}

func firstPositiveInt(text string) (int, bool) {
	for _, match := range positiveIntRe.FindAllString(text, -1) {
		n, err := strconv.Atoi(match)
		if err == nil && n > 0 {
			return n, true
		}
	}
	return 0, false
}

func stripOCRMarkup(ocrText string) string {
	text := htmlTagRe.ReplaceAllString(ocrText, " ")
	text = strings.ReplaceAll(text, "&quot;", `"`)
	text = strings.ReplaceAll(text, "&#34;", `"`)
	text = strings.ReplaceAll(text, "&amp;", "&")
	text = strings.ReplaceAll(text, "&apos;", "'")
	text = strings.ReplaceAll(text, "&#39;", "'")
	return strings.Join(strings.Fields(text), " ")
}

func normalizedContains(text, target string) bool {
	needle := normalizeForEvidence(target)
	if len(needle) < 4 {
		return false
	}
	haystack := normalizeForEvidence(text)
	if strings.Contains(haystack, needle) {
		return true
	}
	return normalizedApproxContains(haystack, needle)
}

func normalizeForEvidence(s string) string {
	var b strings.Builder
	lastSpace := true
	for _, r := range strings.ToLower(s) {
		switch {
		case unicode.IsLetter(r) || unicode.IsDigit(r):
			b.WriteRune(r)
			lastSpace = false
		default:
			if !lastSpace {
				b.WriteByte(' ')
				lastSpace = true
			}
		}
	}
	return strings.TrimSpace(b.String())
}

func normalizedApproxContains(haystack, needle string) bool {
	targetWords := strings.Fields(needle)
	if len(targetWords) < 2 {
		return false
	}
	textWords := strings.Fields(haystack)
	if len(textWords) < len(targetWords) {
		return false
	}

	for i := 0; i <= len(textWords)-len(targetWords); i++ {
		if approxWordSequenceMatch(textWords[i:i+len(targetWords)], targetWords) {
			return true
		}
	}
	return false
}

func approxWordSequenceMatch(candidate, target []string) bool {
	maxTotalDistance := 1
	if len(target) >= 5 {
		maxTotalDistance = 2
	}

	totalDistance := 0
	fuzzyWords := 0
	for i := range target {
		if candidate[i] == target[i] {
			continue
		}
		if len(target[i]) < 5 || len(candidate[i]) < 5 {
			return false
		}
		allowed := 1
		if len(target[i]) >= 10 {
			allowed = 2
		}
		distance := levenshteinDistanceBounded(candidate[i], target[i], allowed)
		if distance > allowed {
			return false
		}
		totalDistance += distance
		fuzzyWords++
		if totalDistance > maxTotalDistance || fuzzyWords > 2 {
			return false
		}
	}
	return totalDistance > 0 && totalDistance <= maxTotalDistance
}

func levenshteinDistanceBounded(a, b string, maxDistance int) int {
	if a == b {
		return 0
	}
	if maxDistance < 0 {
		maxDistance = 0
	}
	ar := []rune(a)
	br := []rune(b)
	if absInt(len(ar)-len(br)) > maxDistance {
		return maxDistance + 1
	}
	if len(ar) == 0 {
		return len(br)
	}
	if len(br) == 0 {
		return len(ar)
	}

	prev := make([]int, len(br)+1)
	curr := make([]int, len(br)+1)
	for j := range prev {
		prev[j] = j
	}
	for i, ra := range ar {
		curr[0] = i + 1
		rowMin := curr[0]
		for j, rb := range br {
			cost := 0
			if ra != rb {
				cost = 1
			}
			curr[j+1] = minInt(
				curr[j]+1,
				minInt(prev[j+1]+1, prev[j]+cost),
			)
			if curr[j+1] < rowMin {
				rowMin = curr[j+1]
			}
		}
		if rowMin > maxDistance {
			return maxDistance + 1
		}
		prev, curr = curr, prev
	}
	return prev[len(br)]
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func absInt(v int) int {
	if v < 0 {
		return -v
	}
	return v
}

func truncateRunes(s string, max int) string {
	if max <= 0 {
		return ""
	}
	runes := []rune(s)
	if len(runes) <= max {
		return s
	}
	return string(runes[:max]) + "..."
}

func clampToolPage(page, totalPages int) int {
	if page < 1 {
		return 1
	}
	if totalPages > 0 && page > totalPages {
		return totalPages
	}
	return page
}

func numberWord(n int) string {
	words := map[int]string{
		1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
		6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
		11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
		16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
		21: "twenty one", 22: "twenty two", 23: "twenty three", 24: "twenty four", 25: "twenty five",
		26: "twenty six", 27: "twenty seven", 28: "twenty eight", 29: "twenty nine", 30: "thirty",
	}
	return words[n]
}

func romanNumeral(n int) string {
	if n <= 0 || n > 39 {
		return ""
	}
	values := []struct {
		value int
		text  string
	}{
		{10, "x"},
		{9, "ix"},
		{5, "v"},
		{4, "iv"},
		{1, "i"},
	}
	var b strings.Builder
	for _, v := range values {
		for n >= v.value {
			b.WriteString(v.text)
			n -= v.value
		}
	}
	return b.String()
}
