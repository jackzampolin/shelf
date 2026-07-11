package tools

import (
	"context"
	"fmt"
	"strconv"
	"strings"
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
