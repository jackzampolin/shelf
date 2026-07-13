package tools

import (
	"context"
	"fmt"
	"unicode/utf8"

	"github.com/jackzampolin/shelf/internal/providers"
)

const maxPageOcrToolTextRunes = 900

func getPageOcrTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "get_page_ocr",
			Description: "Get compact OCR markdown for a specific page, plus evidence about whether it matches the target entry. Use this to verify that a candidate page actually contains the chapter heading (not just a text mention or footnote reference). Check for: heading at top of page, chapter number/title format, body text follows (not citations).",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"page_num": map[string]any{
						"type":        "integer",
						"description": "Page number to get OCR text for",
					},
				},
				"required": []string{"page_num"},
			}),
		},
	}
}

func (t *TocEntryFinderTools) getPageOcr(ctx context.Context, pageNum int) (string, error) {
	if pageNum < 1 || pageNum > t.book.TotalPages {
		return jsonError(fmt.Sprintf("Invalid page number: %d (book has %d pages)", pageNum, t.book.TotalPages)), nil
	}

	text, err := t.getPageOcrMarkdown(ctx, pageNum)
	if err != nil {
		return jsonError(fmt.Sprintf("No OCR data for page %d: %v", pageNum, err)), nil
	}

	backMatterStart := t.effectiveBackMatterStart()
	inBackMatter := backMatterStart > 0 && pageNum >= backMatterStart
	evidence := t.AnalyzePageEvidence(text, pageNum, inBackMatter)
	boundaryErr := t.addPageHeaderBoundaryEvidence(ctx, pageNum, &evidence)
	t.ocrEvidenceByPage[pageNum] = evidence
	ocrText, truncated, omitted := compactPageOcrText(text)

	result := map[string]any{
		"page_num":            pageNum,
		"ocr_text":            ocrText,
		"char_count":          utf8.RuneCountInString(text),
		"ocr_text_truncated":  truncated,
		"omitted_char_count":  omitted,
		"in_back_matter":      inBackMatter,
		"evidence":            evidence,
		"validation_guidance": "If write_result_ready is true, call write_result with write_result_args. Otherwise use evidence.title_in_section_header, evidence.title_prefix_in_section_header, evidence.entry_number_in_section_header, evidence.starts_title_header_cluster, or evidence.expected_printed_page_missing before calling write_result.",
	}
	if ready, args := t.writeResultRecommendation(pageNum, evidence, inBackMatter); ready {
		result["write_result_ready"] = true
		result["write_result_args"] = args
	} else {
		result["write_result_ready"] = false
	}
	if boundaryErr != nil {
		result["boundary_warning"] = boundaryErr.Error()
	}

	if inBackMatter && t.targetIsBackMatter {
		result["note"] = fmt.Sprintf("This page is in the late-section region (page %d+), which is plausible for this target. Verify it is the requested entry start.", backMatterStart)
	} else if inBackMatter {
		result["warning"] = fmt.Sprintf("This page is in the back matter region (page %d+). Check if this is actually the chapter or a footnote/endnote reference.", backMatterStart)
	}

	return jsonSuccess(result), nil
}

func (t *TocEntryFinderTools) writeResultRecommendation(pageNum int, evidence PageEvidence, inBackMatter bool) (bool, map[string]any) {
	if inBackMatter && !t.targetIsBackMatter {
		return false, nil
	}

	reason := ""
	switch {
	case evidence.TitleInSectionHeader:
		reason = "OCR evidence shows a formal section header matching the target title."
	case evidence.TitlePrefixInSectionHeader:
		reason = "OCR evidence shows a formal section header with a distinctive prefix of the target title."
	case evidence.EntryNumberInSectionHeader:
		reason = "OCR evidence shows a formal section header matching the target entry number."
	case evidence.TitleInPageHeader && evidence.StartsTitleHeaderCluster && evidence.ExpectedPrintedPageMissing:
		reason = "OCR evidence shows the first available scanned page after the expected printed page is missing."
	case evidence.TitleInPageHeader && evidence.StartsTitleHeaderCluster:
		reason = "OCR evidence shows the first page of the target title header cluster."
	default:
		return false, nil
	}

	return true, map[string]any{
		"scan_page": pageNum,
		"reasoning": fmt.Sprintf("%s Use scan page %d.", reason, pageNum),
	}
}

func compactPageOcrText(text string) (string, bool, int) {
	runes := []rune(text)
	if len(runes) <= maxPageOcrToolTextRunes {
		return text, false, 0
	}
	omitted := len(runes) - maxPageOcrToolTextRunes
	return string(runes[:maxPageOcrToolTextRunes]) + "\n\n[OCR text truncated; use the evidence fields and page lead above for opener validation.]", true, omitted
}
