package tools

import (
	"context"
	"fmt"
	"regexp"
	"strings"
)

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
	if evidence == nil {
		return nil
	}
	needsLeadBoundary := evidence.TitleAtPageLead &&
		!evidence.TitleInSectionHeader &&
		!evidence.TitlePrefixInSectionHeader &&
		!evidence.EntryNumberInSectionHeader
	if !evidence.TitleInPageHeader && !needsLeadBoundary {
		return nil
	}
	if pageNum <= 1 {
		evidence.StartsTitleHeaderCluster = evidence.TitleInPageHeader
		evidence.StartsTitleLeadCluster = needsLeadBoundary
		return nil
	}
	prevEvidence, err := t.previousPageEvidence(ctx, pageNum)
	if err != nil {
		return fmt.Errorf("could not verify whether page %d starts the title cluster: %w", pageNum, err)
	}
	if evidence.TitleInPageHeader {
		evidence.PreviousPageHeaderText = prevEvidence.PageHeaderText
		evidence.PreviousPrintedPageNumber = prevEvidence.PrintedPageNumber
		evidence.StartsTitleHeaderCluster = !prevEvidence.TitleInPageHeader
	}
	if needsLeadBoundary {
		evidence.StartsTitleLeadCluster = !prevEvidence.TitleAtPageLead
	}

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

func removeLabeledBlocks(ocrText, label string) string {
	return labeledBlockRe(label).ReplaceAllString(ocrText, " ")
}

func labeledBlockRe(label string) *regexp.Regexp {
	return regexp.MustCompile(fmt.Sprintf(`(?is)<[^>]*data-label=["']%s["'][^>]*>(.*?)</[^>]+>`, regexp.QuoteMeta(label)))
}
