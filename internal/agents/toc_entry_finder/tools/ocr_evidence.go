package tools

import (
	"context"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

type ScanWindow struct {
	StartPage int `json:"start_page"`
	EndPage   int `json:"end_page"`
}

type PageEvidence struct {
	TargetTitle                string      `json:"target_title,omitempty"`
	TitleFound                 bool        `json:"title_found"`
	TitleInPageHeader          bool        `json:"title_in_page_header"`
	TitleInSectionHeader       bool        `json:"title_in_section_header"`
	TitlePrefixInSectionHeader bool        `json:"title_prefix_in_section_header"`
	TitleInBody                bool        `json:"title_in_body"`
	EntryNumberFound           bool        `json:"entry_number_found"`
	EntryNumberInSectionHeader bool        `json:"entry_number_in_section_header"`
	PageHeaderText             []string    `json:"page_header_text,omitempty"`
	SectionHeaderText          []string    `json:"section_header_text,omitempty"`
	PrintedPageNumber          int         `json:"printed_page_number,omitempty"`
	PreviousPrintedPageNumber  int         `json:"previous_printed_page_number,omitempty"`
	PreviousPageHeaderText     []string    `json:"previous_page_header_text,omitempty"`
	StartsTitleHeaderCluster   bool        `json:"starts_title_header_cluster,omitempty"`
	ExpectedPrintedPageMissing bool        `json:"expected_printed_page_missing,omitempty"`
	VisibleLead                string      `json:"visible_lead,omitempty"`
	ExpectedScanWindow         *ScanWindow `json:"expected_scan_window,omitempty"`
	InExpectedScanWindow       bool        `json:"in_expected_scan_window,omitempty"`
	DecisionGuidance           string      `json:"decision_guidance,omitempty"`
}

var (
	htmlTagRe             = regexp.MustCompile(`(?s)<[^>]+>`)
	markdownHeadingLineRe = regexp.MustCompile(`(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$`)
	positiveIntRe         = regexp.MustCompile(`\b\d{1,4}\b`)
)

func (t *TocEntryFinderTools) AnalyzePageEvidence(ocrText string, pageNum int, inBackMatter bool) PageEvidence {
	title := ""
	if t.entry != nil {
		title = strings.TrimSpace(t.entry.Title)
	}

	pageHeaders := extractPageHeaders(ocrText)
	pageHeaderText := strings.Join(pageHeaders, " ")
	sectionHeaders := extractSectionHeaders(ocrText)
	sectionHeaderText := strings.Join(sectionHeaders, " ")
	plainText := stripOCRMarkup(ocrText)
	bodyText := stripOCRMarkup(removeLabeledBlocks(removeLabeledBlocks(removeLabeledBlocks(ocrText, "Page-Header"), "Page-Footer"), "Section-Header"))

	evidence := PageEvidence{
		TargetTitle:                title,
		PageHeaderText:             pageHeaders,
		SectionHeaderText:          sectionHeaders,
		PrintedPageNumber:          printedPageNumberFromHeaders(pageHeaders),
		VisibleLead:                truncateRunes(plainText, 260),
		TitleInPageHeader:          normalizedContains(pageHeaderText, title),
		TitleInSectionHeader:       normalizedContains(sectionHeaderText, title),
		TitlePrefixInSectionHeader: sectionHeaderMatchesTitlePrefix(sectionHeaders, title, t.entryNumber()),
		TitleInBody:                normalizedContains(bodyText, title),
		EntryNumberFound:           t.entryNumberFound(plainText),
	}
	entryNumberInSectionHeader := t.entryNumberFound(sectionHeaderText)
	if !entryNumberInSectionHeader && evidence.TitlePrefixInSectionHeader {
		entryNumberInSectionHeader = t.entryNumberPrefixInSectionHeader(sectionHeaders)
	}
	evidence.EntryNumberInSectionHeader = entryNumberInSectionHeader
	evidence.TitleFound = evidence.TitleInPageHeader || evidence.TitleInSectionHeader || evidence.TitlePrefixInSectionHeader || evidence.TitleInBody

	if start, end, ok := t.expectedScanWindow(); ok {
		evidence.ExpectedScanWindow = &ScanWindow{StartPage: start, EndPage: end}
		evidence.InExpectedScanWindow = pageNum >= start && pageNum <= end
	}

	switch {
	case evidence.TitlePrefixInSectionHeader:
		evidence.DecisionGuidance = "A formal section header contains a distinctive prefix of the target title. This is strong evidence for appendix/diagram entries whose title continues on an adjacent page."
	case evidence.TitleInSectionHeader || evidence.EntryNumberInSectionHeader:
		evidence.DecisionGuidance = "A formal section header matches the target title or entry number. This is strong evidence that this page is the entry opener."
	case evidence.TitleInPageHeader && evidence.InExpectedScanWindow && !inBackMatter:
		evidence.DecisionGuidance = "Target title appears in a page header inside the expected scan window. This is only enough evidence if this page starts the title cluster; repeated running headers on later pages will be rejected."
	case evidence.TitleInPageHeader && !inBackMatter:
		evidence.DecisionGuidance = "Target title appears in a page header. Verify this is the first page of the target's grep cluster before calling write_result; repeated running headers are not entry openers."
	case evidence.TitleFound && !inBackMatter:
		evidence.DecisionGuidance = "Target title appears on this page, but not as a formal section header. Confirm it is an opener rather than an incidental body-text reference."
	case inBackMatter && !t.targetIsBackMatter:
		evidence.DecisionGuidance = "This is a back-matter page for a non-back-matter target. Prefer earlier in-book evidence unless OCR clearly shows this exact entry starts here."
	default:
		evidence.DecisionGuidance = "Target title is not visible in the OCR text for this page."
	}

	return evidence
}

func (t *TocEntryFinderTools) ValidateCandidatePage(ctx context.Context, scanPage int) (PageEvidence, string, error) {
	if t == nil || t.book == nil {
		return PageEvidence{}, "missing book state for validation", nil
	}
	if scanPage < 1 || scanPage > t.book.TotalPages {
		return PageEvidence{}, fmt.Sprintf("scan_page %d is outside book range 1-%d", scanPage, t.book.TotalPages), nil
	}

	backMatterStart := t.effectiveBackMatterStart()
	inBackMatter := backMatterStart > 0 && scanPage >= backMatterStart
	if inBackMatter && !t.targetIsBackMatter {
		return PageEvidence{}, fmt.Sprintf("page is in the late/back-matter region starting at scan page %d, but this target is a body entry", backMatterStart), nil
	}

	evidence, err := t.pageEvidence(ctx, scanPage, inBackMatter)
	if err != nil {
		return PageEvidence{}, "", err
	}
	if err := t.addPageHeaderBoundaryEvidence(ctx, scanPage, &evidence); err != nil {
		return evidence, "", err
	}
	if evidence.TitleInSectionHeader || evidence.TitlePrefixInSectionHeader || evidence.EntryNumberInSectionHeader {
		return evidence, "", nil
	}

	if evidence.TitleInPageHeader {
		if !evidence.StartsTitleHeaderCluster {
			return evidence, fmt.Sprintf("page header/title also appears on previous page %d, so scan_page %d looks like a repeated running header instead of the entry opener", scanPage-1, scanPage), nil
		}
		return evidence, "", nil
	}

	if evidence.EntryNumberFound {
		return evidence, "entry number appears only outside a formal section header; use get_page_ocr near the grep cluster and choose the page with the chapter/section heading", nil
	}
	if evidence.TitleFound {
		return evidence, "target title appears only outside a page header or formal section header; body-text mentions are not enough to link the ToC entry", nil
	}
	return evidence, "OCR evidence on this page does not contain the target title or entry number", nil
}

func (t *TocEntryFinderTools) pageEvidence(ctx context.Context, pageNum int, inBackMatter bool) (PageEvidence, error) {
	if evidence, ok := t.ocrEvidenceByPage[pageNum]; ok {
		return evidence, nil
	}
	text, err := t.getPageOcrMarkdown(ctx, pageNum)
	if err != nil {
		return PageEvidence{}, fmt.Errorf("could not load OCR for page %d: %w", pageNum, err)
	}
	evidence := t.AnalyzePageEvidence(text, pageNum, inBackMatter)
	t.ocrEvidenceByPage[pageNum] = evidence
	return evidence, nil
}

func (t *TocEntryFinderTools) addPageHeaderBoundaryEvidence(ctx context.Context, pageNum int, evidence *PageEvidence) error {
	if evidence == nil || !evidence.TitleInPageHeader || pageNum <= 1 {
		return nil
	}
	prevEvidence, err := t.previousPageEvidence(ctx, pageNum)
	if err != nil {
		return fmt.Errorf("could not verify whether page %d starts the title cluster: %w", pageNum, err)
	}
	evidence.PreviousPageHeaderText = prevEvidence.PageHeaderText
	evidence.PreviousPrintedPageNumber = prevEvidence.PrintedPageNumber
	evidence.StartsTitleHeaderCluster = !prevEvidence.TitleFound

	targetPrinted, ok := t.targetPrintedPageNumber()
	if ok && prevEvidence.PrintedPageNumber > 0 && evidence.PrintedPageNumber > 0 &&
		prevEvidence.PrintedPageNumber < targetPrinted && targetPrinted < evidence.PrintedPageNumber {
		evidence.ExpectedPrintedPageMissing = true
	}

	if evidence.StartsTitleHeaderCluster && evidence.ExpectedPrintedPageMissing {
		evidence.DecisionGuidance = fmt.Sprintf("Target title starts a new page-header cluster here. The previous scan page is printed %d and this page is printed %d, so expected printed page %d is absent from the scan set; if no formal section header is available, this is the first available scanned page for the entry.",
			prevEvidence.PrintedPageNumber, evidence.PrintedPageNumber, targetPrinted)
	} else if evidence.StartsTitleHeaderCluster {
		evidence.DecisionGuidance = "Target title starts a new page-header cluster here. If no formal section/chapter header is available, this first cluster page is acceptable; later repeated running headers are not."
	}
	return nil
}

func (t *TocEntryFinderTools) previousPageEvidence(ctx context.Context, pageNum int) (PageEvidence, error) {
	if pageNum <= 1 {
		return PageEvidence{}, nil
	}
	prevPage := pageNum - 1
	backMatterStart := t.effectiveBackMatterStart()
	prevInBackMatter := backMatterStart > 0 && prevPage >= backMatterStart
	return t.pageEvidence(ctx, prevPage, prevInBackMatter)
}

func (t *TocEntryFinderTools) expectedScanWindow() (int, int, bool) {
	if t == nil || t.entry == nil || t.book == nil || t.book.TotalPages <= 0 {
		return 0, 0, false
	}
	if strings.TrimSpace(t.entry.PrintedPageNumber) == "" {
		return 0, 0, false
	}
	printedPage, ok := t.targetPrintedPageNumber()
	if !ok {
		return 0, 0, false
	}
	start := clampToolPage(printedPage+10, t.book.TotalPages)
	end := clampToolPage(printedPage+35, t.book.TotalPages)
	if end < start {
		end = start
	}
	return start, end, true
}

func (t *TocEntryFinderTools) targetPrintedPageNumber() (int, bool) {
	if t == nil || t.entry == nil {
		return 0, false
	}
	printedPage, err := strconv.Atoi(strings.TrimSpace(t.entry.PrintedPageNumber))
	if err != nil || printedPage <= 0 {
		return 0, false
	}
	return printedPage, true
}

func (t *TocEntryFinderTools) entryNumberFound(text string) bool {
	entryNumber := t.entryNumber()
	if entryNumber == "" {
		return false
	}
	levelName := strings.TrimSpace(t.entry.LevelName)
	if levelName == "" {
		levelName = "chapter"
	}

	normalizedText := normalizeForEvidence(text)
	parts := []string{entryNumber}
	if n, err := strconv.Atoi(entryNumber); err == nil {
		parts = append(parts, numberWord(n), romanNumeral(n))
	}

	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if strings.Contains(normalizedText, normalizeForEvidence(fmt.Sprintf("%s %s", levelName, part))) {
			return true
		}
	}
	return false
}

func (t *TocEntryFinderTools) entryNumber() string {
	if t == nil || t.entry == nil {
		return ""
	}
	return strings.TrimSpace(t.entry.EntryNumber)
}

func (t *TocEntryFinderTools) entryNumberPrefixInSectionHeader(headers []string) bool {
	entryNumber := normalizeForEvidence(t.entryNumber())
	if entryNumber == "" {
		return false
	}
	for _, header := range headers {
		normalizedHeader := normalizeForEvidence(header)
		if normalizedHeader == entryNumber || strings.HasPrefix(normalizedHeader, entryNumber+" ") {
			return true
		}
	}
	return false
}

func extractPageHeaders(ocrText string) []string {
	headers := extractLabeledBlocks(ocrText, "Page-Header")
	headers = append(headers, extractLabeledBlocks(ocrText, "Page-Footer")...)
	return headers
}

func extractSectionHeaders(ocrText string) []string {
	headers := extractLabeledBlocks(ocrText, "Section-Header")
	for _, match := range markdownHeadingLineRe.FindAllStringSubmatch(ocrText, -1) {
		if len(match) < 2 {
			continue
		}
		header := strings.TrimSpace(stripOCRMarkup(match[1]))
		if header != "" {
			headers = append(headers, header)
		}
	}
	return headers
}

func extractLabeledBlocks(ocrText, label string) []string {
	matches := labeledBlockRe(label).FindAllStringSubmatch(ocrText, -1)
	if len(matches) == 0 {
		return nil
	}
	blocks := make([]string, 0, len(matches))
	for _, match := range matches {
		if len(match) < 2 {
			continue
		}
		block := strings.TrimSpace(stripOCRMarkup(match[1]))
		if block != "" {
			blocks = append(blocks, block)
		}
	}
	return blocks
}

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

func removeLabeledBlocks(ocrText, label string) string {
	return labeledBlockRe(label).ReplaceAllString(ocrText, " ")
}

func labeledBlockRe(label string) *regexp.Regexp {
	return regexp.MustCompile(fmt.Sprintf(`(?is)<[^>]*data-label=["']%s["'][^>]*>(.*?)</[^>]+>`, regexp.QuoteMeta(label)))
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
