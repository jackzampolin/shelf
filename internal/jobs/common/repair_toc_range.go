package common

import (
	"context"
	"fmt"
	"strings"
	"time"
)

// TocRangeRepairResult describes a durable operator override of ToC discovery.
type TocRangeRepairResult struct {
	TocDocID  string
	StartPage int
	EndPage   int
	Reason    string
	CID       string
}

// ValidateTocRangeRepair verifies that an operator-selected range is usable by
// ToC extraction. Every selected page must be terminal OCR, non-quarantined,
// and contain persisted text.
func ValidateTocRangeRepair(ctx context.Context, book *BookState, startPage, endPage int, reason string) error {
	if book == nil {
		return fmt.Errorf("book state is required")
	}
	if book.TocDocID() == "" {
		return fmt.Errorf("book has no ToC record")
	}
	if startPage < 1 || endPage < startPage || endPage > book.TotalPages {
		return fmt.Errorf("ToC range %d-%d is outside valid range 1-%d", startPage, endPage, book.TotalPages)
	}
	if strings.TrimSpace(reason) == "" {
		return fmt.Errorf("repair reason is required")
	}

	for pageNum := startPage; pageNum <= endPage; pageNum++ {
		page := book.GetPage(pageNum)
		if page == nil {
			return fmt.Errorf("page %d is missing", pageNum)
		}
		if quarantined, quarantineReason := page.OCRQuarantine(); quarantined {
			return fmt.Errorf("page %d is OCR-quarantined: %s", pageNum, quarantineReason)
		}
		if !page.OcrResolved(book.OcrProviders) {
			return fmt.Errorf("page %d does not have terminal OCR", pageNum)
		}
		markdown, err := book.GetOcrMarkdown(ctx, pageNum)
		if err != nil {
			return fmt.Errorf("read OCR text for page %d: %w", pageNum, err)
		}
		if strings.TrimSpace(markdown) == "" {
			return fmt.Errorf("page %d has no OCR text", pageNum)
		}
	}
	return nil
}

// RepairTocRange replaces ToC finder output with a source-backed operator
// range, clears extraction and every downstream artifact, and records durable
// override provenance. The caller is responsible for stopping any active job
// before calling and submitting a replacement job afterward.
func RepairTocRange(ctx context.Context, book *BookState, startPage, endPage int, reason string) (*TocRangeRepairResult, error) {
	if err := ValidateTocRangeRepair(ctx, book, startPage, endPage, reason); err != nil {
		return nil, err
	}

	tocDocID := book.TocDocID()
	if err := ResetFrom(ctx, book, tocDocID, ResetTocExtract); err != nil {
		return nil, fmt.Errorf("reset ToC extraction: %w", err)
	}

	reason = strings.TrimSpace(reason)
	fields := map[string]any{
		"toc_found":              true,
		"start_page":             startPage,
		"end_page":               endPage,
		"structure_summary":      nil,
		"finder_started":         false,
		"finder_complete":        true,
		"finder_failed":          false,
		"finder_retries":         0,
		"finder_override":        true,
		"finder_override_reason": reason,
		"finder_override_at":     time.Now().UTC().Format(time.RFC3339),
	}
	cid, err := book.PersistTocFinderResult(ctx, true, startPage, endPage, fields)
	if err != nil {
		return nil, fmt.Errorf("persist ToC finder override: %w", err)
	}
	book.SetOpState(OpTocFinder, false, true, false, 0)

	return &TocRangeRepairResult{
		TocDocID:  tocDocID,
		StartPage: startPage,
		EndPage:   endPage,
		Reason:    reason,
		CID:       cid,
	}, nil
}
