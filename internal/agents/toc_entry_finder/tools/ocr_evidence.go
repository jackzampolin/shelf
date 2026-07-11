package tools

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
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
	TitleAtPageLead            bool        `json:"title_at_page_lead"`
	TitleInBody                bool        `json:"title_in_body"`
	EntryNumberFound           bool        `json:"entry_number_found"`
	EntryNumberInSectionHeader bool        `json:"entry_number_in_section_header"`
	PageHeaderText             []string    `json:"page_header_text,omitempty"`
	SectionHeaderText          []string    `json:"section_header_text,omitempty"`
	PrintedPageNumber          int         `json:"printed_page_number,omitempty"`
	PreviousPrintedPageNumber  int         `json:"previous_printed_page_number,omitempty"`
	PreviousPageHeaderText     []string    `json:"previous_page_header_text,omitempty"`
	StartsTitleHeaderCluster   bool        `json:"starts_title_header_cluster,omitempty"`
	StartsTitleLeadCluster     bool        `json:"starts_title_lead_cluster,omitempty"`
	LooksLikeContentsPage      bool        `json:"looks_like_contents_page,omitempty"`
	ExpectedPrintedPageMissing bool        `json:"expected_printed_page_missing,omitempty"`
	VisibleLead                string      `json:"visible_lead,omitempty"`
	ExpectedScanWindow         *ScanWindow `json:"expected_scan_window,omitempty"`
	InExpectedScanWindow       bool        `json:"in_expected_scan_window,omitempty"`
	DecisionGuidance           string      `json:"decision_guidance,omitempty"`
}

func (t *TocEntryFinderTools) AnalyzePageEvidence(ocrText string, pageNum int, inBackMatter bool) PageEvidence {
	title := ""
	if t.entry != nil {
		title = strings.TrimSpace(t.entry.Title)
	}

	pageHeaders := extractPageHeaders(ocrText)
	pageHeaderText := strings.Join(pageHeaders, " ")
	sectionHeaders := extractSectionHeaders(ocrText)
	if header := unlabeledStandaloneTitleBlock(ocrText, title); header != "" {
		sectionHeaders = append(sectionHeaders, header)
	}
	sectionHeaderText := strings.Join(sectionHeaders, " ")
	plainText := stripOCRMarkup(ocrText)
	normalizedPlainText := normalizeForEvidence(plainText)
	normalizedTitle := normalizeForEvidence(title)
	bodyText := stripOCRMarkup(removeLabeledBlocks(removeLabeledBlocks(removeLabeledBlocks(ocrText, "Page-Header"), "Page-Footer"), "Section-Header"))
	numberedLevelTitleMatch := sectionHeaderMatchesNumberedLevelTitle(sectionHeaders, title, t.entryLevelName(), plainText)

	evidence := PageEvidence{
		TargetTitle:                title,
		PageHeaderText:             pageHeaders,
		SectionHeaderText:          sectionHeaders,
		PrintedPageNumber:          printedPageNumberFromHeaders(pageHeaders),
		VisibleLead:                truncateRunes(plainText, 260),
		TitleInPageHeader:          normalizedContains(pageHeaderText, title),
		TitleInSectionHeader:       normalizedContains(sectionHeaderText, title) || numberedLevelTitleMatch,
		TitlePrefixInSectionHeader: sectionHeaderMatchesTitlePrefix(sectionHeaders, title, t.entryNumber()),
		TitleAtPageLead:            normalizedTitleAtPageLead(normalizedPlainText, normalizedTitle),
		TitleInBody:                normalizedContains(bodyText, title),
		EntryNumberFound:           t.entryNumberFound(plainText),
		LooksLikeContentsPage:      looksLikeContentsPage(normalizedPlainText),
	}
	entryNumberInSectionHeader := t.entryNumberFound(sectionHeaderText)
	if !entryNumberInSectionHeader && evidence.TitlePrefixInSectionHeader {
		entryNumberInSectionHeader = t.entryNumberPrefixInSectionHeader(sectionHeaders)
	}
	evidence.EntryNumberInSectionHeader = entryNumberInSectionHeader
	evidence.TitleFound = evidence.TitleInPageHeader || evidence.TitleInSectionHeader || evidence.TitlePrefixInSectionHeader || evidence.TitleAtPageLead || evidence.TitleInBody

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
	case evidence.TitleAtPageLead && !evidence.LooksLikeContentsPage:
		evidence.DecisionGuidance = "The exact target title appears at the start of unlabeled OCR. Verify the previous page does not start with the same title; contents listings and repeated running leads are rejected."
	case evidence.TitleFound && !inBackMatter:
		evidence.DecisionGuidance = "Target title appears on this page, but not as a formal section header. Confirm it is an opener rather than an incidental body-text reference."
	case inBackMatter && !t.targetIsBackMatter:
		evidence.DecisionGuidance = "This is a back-matter page for a non-back-matter target. Prefer earlier in-book evidence unless OCR clearly shows this exact entry starts here."
	default:
		evidence.DecisionGuidance = "Target title is not visible in the OCR text for this page."
	}

	return evidence
}

const minStandaloneHeadingPrefixRunes = 100

// unlabeledStandaloneTitleBlock recognizes a conservative enriched-PDF shape:
// an exact all-caps ToC title after a blank separator and substantive text.
// Some PDFs preserve the visual centered heading but emit no Markdown or
// data-label marker, and some omit the blank line between that heading and its
// first paragraph. Requiring an exact, all-caps line or block away from the page
// lead keeps ordinary prose mentions and repeated running headers out.
func unlabeledStandaloneTitleBlock(ocrText, title string) string {
	target := normalizeForEvidence(title)
	if len(target) < 4 {
		return ""
	}

	text := strings.ReplaceAll(ocrText, "\r\n", "\n")
	text = strings.ReplaceAll(text, "\r", "\n")
	lines := strings.Split(text, "\n")
	prefixRunes := 0
	for i := 0; i < len(lines); {
		for i < len(lines) && strings.TrimSpace(stripOCRMarkup(lines[i])) == "" {
			i++
		}
		if i >= len(lines) {
			break
		}

		start := i
		firstLine := strings.TrimSpace(stripOCRMarkup(lines[start]))
		if start > 0 &&
			strings.TrimSpace(stripOCRMarkup(lines[start-1])) == "" &&
			prefixRunes >= minStandaloneHeadingPrefixRunes &&
			normalizeForEvidence(firstLine) == target &&
			allCapsHeading(firstLine) {
			return firstLine
		}
		blockLines := make([]string, 0, 2)
		for i < len(lines) {
			line := strings.TrimSpace(stripOCRMarkup(lines[i]))
			if line == "" {
				break
			}
			blockLines = append(blockLines, line)
			i++
		}
		block := strings.Join(blockLines, " ")
		if start > 0 && i < len(lines) &&
			prefixRunes >= minStandaloneHeadingPrefixRunes &&
			normalizeForEvidence(block) == target &&
			allCapsHeading(block) {
			return block
		}
		prefixRunes += utf8.RuneCountInString(block)
	}
	return ""
}

func allCapsHeading(text string) bool {
	letters := 0
	for _, r := range text {
		if !unicode.IsLetter(r) {
			continue
		}
		letters++
		if unicode.IsLower(r) {
			return false
		}
	}
	return letters >= 4
}

func (t *TocEntryFinderTools) ValidateCandidatePage(ctx context.Context, scanPage int) (PageEvidence, string, error) {
	if t == nil || t.book == nil {
		return PageEvidence{}, "missing book state for validation", nil
	}
	if scanPage < 1 || scanPage > t.book.TotalPages {
		return PageEvidence{}, fmt.Sprintf("scan_page %d is outside book range 1-%d", scanPage, t.book.TotalPages), nil
	}
	if tocStart, tocEnd := t.book.GetTocPageRange(); tocStart > 0 && tocEnd >= tocStart && scanPage >= tocStart && scanPage <= tocEnd {
		return PageEvidence{}, fmt.Sprintf("scan_page %d is inside the detected contents range %d-%d, not an entry opener", scanPage, tocStart, tocEnd), nil
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
	if evidence.TitleAtPageLead {
		if evidence.LooksLikeContentsPage {
			return evidence, "the target appears near the top of a contents listing, not an entry opener", nil
		}
		if !evidence.StartsTitleLeadCluster {
			return evidence, fmt.Sprintf("the target also appears at the lead of previous page %d, so scan_page %d looks like a repeated running lead instead of the entry opener", scanPage-1, scanPage), nil
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

const maxNormalizedTitleLeadOffset = 80

func normalizedTitleAtPageLead(normalizedText, normalizedTitle string) bool {
	if normalizedText == "" || normalizedTitle == "" {
		return false
	}
	idx := strings.Index(normalizedText, normalizedTitle)
	if idx >= 0 {
		return idx <= maxNormalizedTitleLeadOffset
	}
	// Reuse the bounded OCR typo matcher, but only over enough leading text to
	// contain the title plus a short level/number prefix. This admits a source
	// opener such as "Defeating Germany and Javan" for target "...Japan"
	// without turning a later body mention into lead evidence.
	leadEnd := maxNormalizedTitleLeadOffset + len(normalizedTitle) + 40
	if leadEnd > len(normalizedText) {
		leadEnd = len(normalizedText)
	}
	return normalizedApproxContains(normalizedText[:leadEnd], normalizedTitle)
}

func looksLikeContentsPage(normalizedText string) bool {
	if normalizedText == "" {
		return false
	}
	for _, marker := range []string{"table of contents", "contents"} {
		idx := strings.Index(normalizedText, marker)
		if idx >= 0 && idx <= maxNormalizedTitleLeadOffset {
			return true
		}
	}
	return false
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

func (t *TocEntryFinderTools) entryLevelName() string {
	if t == nil || t.entry == nil {
		return ""
	}
	return strings.TrimSpace(t.entry.LevelName)
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
