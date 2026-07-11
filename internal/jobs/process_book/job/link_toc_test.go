package job

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/agent"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
)

func TestValidTocLinkResultRequiresScanPage(t *testing.T) {
	page := 42

	tests := []struct {
		name      string
		result    *agent.Result
		wantError string
	}{
		{
			name:      "nil result",
			result:    nil,
			wantError: "no result",
		},
		{
			name: "agent failure",
			result: &agent.Result{
				Success: false,
				Error:   "max iterations",
			},
			wantError: "max iterations",
		},
		{
			name: "wrong result type",
			result: &agent.Result{
				Success:    true,
				ToolResult: "not a toc result",
			},
			wantError: "unexpected result type",
		},
		{
			name: "nil scan page",
			result: &agent.Result{
				Success: true,
				ToolResult: &toc_entry_finder.Result{
					Reasoning: "not found",
				},
			},
			wantError: "without scan_page",
		},
		{
			name: "valid",
			result: &agent.Result{
				Success: true,
				ToolResult: &toc_entry_finder.Result{
					ScanPage:  &page,
					Reasoning: "found",
				},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := validTocLinkResult(tt.result)
			if tt.wantError != "" {
				if err == nil {
					t.Fatalf("expected error containing %q", tt.wantError)
				}
				if !strings.Contains(err.Error(), tt.wantError) {
					t.Fatalf("expected error containing %q, got %q", tt.wantError, err.Error())
				}
				return
			}
			if err != nil {
				t.Fatalf("expected valid result, got error: %v", err)
			}
			if got == nil || got.ScanPage == nil || *got.ScanPage != page {
				t.Fatalf("unexpected valid result: %#v", got)
			}
		})
	}
}

func TestMaxRetriesForPageWorkUnitUsesOCRSpecificCap(t *testing.T) {
	if got := maxRetriesForPageWorkUnit(WorkUnitTypeOCR); got != MaxOCRPageRetries {
		t.Fatalf("OCR retries = %d, want %d", got, MaxOCRPageRetries)
	}
	if got := maxRetriesForPageWorkUnit(WorkUnitTypeExtract); got != MaxPageOpRetries {
		t.Fatalf("extract retries = %d, want %d", got, MaxPageOpRetries)
	}
}

func TestValidateTocLinkEvidenceRejectsPageWithoutTargetEvidence(t *testing.T) {
	entry := &toc_entry_finder.TocEntry{
		DocID:             "entry-1",
		EntryNumber:       "5",
		LevelName:         "chapter",
		Title:             `PLANNING "TORCH"`,
		PrintedPageNumber: "83",
	}
	j, _ := newTocRecoveryJob([]*toc_entry_finder.TocEntry{entry})
	j.Book.TotalPages = 615
	j.Book.GetOrCreatePage(93).SetOcrMarkdown(`<div data-label="Page-Header">Platform for Invasion</div>
<div data-label="Text"><p>Discussion of cross-Channel planning continued.</p></div>`)

	err := j.validateTocLinkEvidence(context.Background(), entry, 93)
	if err == nil {
		t.Fatal("expected validation to reject page without target evidence")
	}
	if !strings.Contains(err.Error(), "does not contain the target title or entry number") {
		t.Fatalf("unexpected validation error: %v", err)
	}
}

func TestValidateTocLinkEvidenceAcceptsTitleHeader(t *testing.T) {
	entry := &toc_entry_finder.TocEntry{
		DocID:             "entry-1",
		EntryNumber:       "5",
		LevelName:         "chapter",
		Title:             `PLANNING "TORCH"`,
		PrintedPageNumber: "83",
	}
	j, _ := newTocRecoveryJob([]*toc_entry_finder.TocEntry{entry})
	j.Book.TotalPages = 615
	j.Book.GetOrCreatePage(99).SetOcrMarkdown(`<div data-label="Page-Header">Platform for Invasion</div>
<div data-label="Text"><p>The previous chapter continued.</p></div>`)
	j.Book.GetOrCreatePage(100).SetOcrMarkdown(`<div data-label="Page-Header">Planning 'Torch'</div>
<div data-label="Text"><p>At Allied headquarters the next operation took shape.</p></div>`)

	if err := j.validateTocLinkEvidence(context.Background(), entry, 100); err != nil {
		t.Fatalf("expected validation to accept matching page, got: %v", err)
	}
}

func TestValidateTocLinkEvidenceRejectsRepeatedRunningHeader(t *testing.T) {
	entry := &toc_entry_finder.TocEntry{
		DocID:             "entry-1",
		EntryNumber:       "6",
		LevelName:         "chapter",
		Title:             "Invasion of Africa",
		PrintedPageNumber: "114",
	}
	j, _ := newTocRecoveryJob([]*toc_entry_finder.TocEntry{entry})
	j.Book.TotalPages = 615
	j.Book.GetOrCreatePage(129).SetOcrMarkdown(`<div data-label="Page-Header">Invasion of Africa</div>
<div data-label="Text"><p>The campaign was now well underway.</p></div>`)
	j.Book.GetOrCreatePage(130).SetOcrMarkdown(`<div data-label="Page-Header">Invasion of Africa</div>
<div data-label="Text"><p>Another paragraph continued the same chapter.</p></div>`)

	err := j.validateTocLinkEvidence(context.Background(), entry, 130)
	if err == nil {
		t.Fatal("expected validation to reject repeated running header")
	}
	if !strings.Contains(err.Error(), "repeated running header") {
		t.Fatalf("unexpected validation error: %v", err)
	}
}

func TestValidateTocLinkEvidenceAcceptsFormalSectionHeader(t *testing.T) {
	entry := &toc_entry_finder.TocEntry{
		DocID:             "entry-1",
		EntryNumber:       "6",
		LevelName:         "chapter",
		Title:             "Invasion of Africa",
		PrintedPageNumber: "114",
	}
	j, _ := newTocRecoveryJob([]*toc_entry_finder.TocEntry{entry})
	j.Book.TotalPages = 615
	j.Book.GetOrCreatePage(125).SetOcrMarkdown(`<div data-label="Section-Header">CHAPTER SIX</div>
<div data-label="Section-Header">Invasion of Africa</div>
<div data-label="Text"><p>The invasion opened in North Africa.</p></div>`)

	if err := j.validateTocLinkEvidence(context.Background(), entry, 125); err != nil {
		t.Fatalf("expected validation to accept formal section header, got: %v", err)
	}
}

func TestValidateTocLinkEvidenceAcceptsMissingExpectedPrintedPageBoundary(t *testing.T) {
	entry := &toc_entry_finder.TocEntry{
		DocID:             "entry-1",
		EntryNumber:       "7",
		LevelName:         "chapter",
		Title:             "WINTER IN ALGIERS",
		PrintedPageNumber: "128",
	}
	j, _ := newTocRecoveryJob([]*toc_entry_finder.TocEntry{entry})
	j.Book.TotalPages = 615
	j.Book.GetOrCreatePage(146).SetOcrMarkdown(`<div data-label="Page-Header">Invasion of Africa</div>
<div data-label="Page-Header">127</div>
<div data-label="Text"><p>In the eastern sector, Tunisia, it was different.</p></div>`)
	j.Book.GetOrCreatePage(147).SetOcrMarkdown(`<div data-label="Page-Header">Winter in Algiers</div>
<div data-label="Page-Header">129</div>
<div data-label="Text"><p>The air power of the Axis in Sicily remained strong.</p></div>`)

	if err := j.validateTocLinkEvidence(context.Background(), entry, 147); err != nil {
		t.Fatalf("expected validation to accept first available scan page after missing printed page, got: %v", err)
	}
}

func TestValidateTocLinkEvidenceAcceptsAppendixTitlePrefixSectionHeader(t *testing.T) {
	entry := &toc_entry_finder.TocEntry{
		DocID:             "entry-1",
		EntryNumber:       "B",
		LevelName:         "appendix",
		Title:             "The Allied Air-ground Team for the Final Offensive",
		PrintedPageNumber: "552",
		SortOrder:         2900,
	}
	j, _ := newTocRecoveryJob([]*toc_entry_finder.TocEntry{
		{DocID: "appendices", Title: "APPENDICES", SortOrder: 2700},
		entry,
	})
	j.Book.TotalPages = 615
	j.Book.GetOrCreatePage(586).SetOcrMarkdown(`<div data-label="Page-Header">552</div>
<div data-label="Section-Header"><h2>B. THE ALLIED AIR-GROUND TEAM</h2></div>
<div data-label="Diagram"><pre>SUPREME HEADQUARTERS ALLIED</pre></div>`)

	if err := j.validateTocLinkEvidence(context.Background(), entry, 586); err != nil {
		t.Fatalf("expected validation to accept appendix title prefix, got: %v", err)
	}
}

func TestValidateTocLinkEvidenceUsesFullTocSequenceAfterResume(t *testing.T) {
	entry := &toc_entry_finder.TocEntry{
		DocID:             "entry-b",
		EntryNumber:       "B",
		LevelName:         "appendix",
		Title:             "The Allied Air-ground Team for the Final Offensive",
		PrintedPageNumber: "552",
		SortOrder:         2900,
	}
	j, _ := newTocRecoveryJob([]*toc_entry_finder.TocEntry{entry})
	j.Book.TotalPages = 615
	j.Book.SetLinkedEntries([]*common.LinkedTocEntry{
		{DocID: "entry-appendices", Title: "APPENDICES", SortOrder: 2700},
		{
			DocID:             entry.DocID,
			EntryNumber:       entry.EntryNumber,
			Title:             entry.Title,
			LevelName:         entry.LevelName,
			PrintedPageNumber: entry.PrintedPageNumber,
			SortOrder:         entry.SortOrder,
		},
	})
	j.Book.GetOrCreatePage(586).SetOcrMarkdown(`<div data-label="Page-Header">552</div>
<div data-label="Section-Header"><h2>B. THE ALLIED AIR-GROUND TEAM</h2></div>
<div data-label="Diagram"><pre>SUPREME HEADQUARTERS ALLIED</pre></div>`)

	structure := j.tocEntryBookStructure(context.Background(), entry)
	if structure == nil || !structure.TargetIsBackMatter {
		t.Fatalf("expected resumed pending appendix entry to be classified as back matter, got %#v", structure)
	}

	if err := j.validateTocLinkEvidence(context.Background(), entry, 586); err != nil {
		t.Fatalf("expected validation to accept resumed appendix child entry, got: %v", err)
	}
}

func TestBackMatterContextUsesPatternAnalysisAndTocSequence(t *testing.T) {
	pattern := &common.FinalizePatternResult{
		Excluded: []common.ExcludedRange{
			{StartPage: 557, EndPage: 581, Reason: "Footnotes section"},
			{StartPage: 582, EndPage: 589, Reason: "Appendices section"},
			{StartPage: 590, EndPage: 592, Reason: "Glossary section"},
			{StartPage: 593, EndPage: 615, Reason: "Index section"},
		},
	}

	entries := []*toc_entry_finder.TocEntry{
		{Title: "RUSSIA", SortOrder: 2400},
		{Title: "ACKNOWLEDGMENTS", SortOrder: 2500},
		{Title: "FOOTNOTES", SortOrder: 2600},
		{Title: "APPENDICES", SortOrder: 2700},
		{Title: "The German Ground Forces", SortOrder: 3000},
		{Title: "INDEX", SortOrder: 3200},
	}

	if got := deriveBackMatterStart(615, pattern); got != 557 {
		t.Fatalf("deriveBackMatterStart = %d, want 557", got)
	}

	labels := deriveBackMatterTypes(pattern, entries)
	for _, want := range []string{"acknowledgments", "footnotes", "appendices", "glossary", "index"} {
		if !strings.Contains(labels, want) {
			t.Fatalf("deriveBackMatterTypes missing %q in %q", want, labels)
		}
	}

	if tocEntryIsBackMatter(entries[0], entries) {
		t.Fatal("RUSSIA should not be treated as back matter")
	}
	if !tocEntryIsBackMatter(entries[4], entries) {
		t.Fatal("appendix child entry should be treated as back matter")
	}
}

func TestUnsafePatternExclusionsCannotMoveBackMatterIntoBody(t *testing.T) {
	pattern := &common.FinalizePatternResult{
		Excluded: []common.ExcludedRange{
			{StartPage: 8, EndPage: 413, Reason: "Prefaces and Abbreviations at the front matter"},
			{StartPage: 16, EndPage: 413, Reason: "Contents/Table of Contents page"},
			{StartPage: 23, EndPage: 411, Reason: "Main text ends at p409, Appendix starts p412"},
			{StartPage: 412, EndPage: 413, Reason: "Appendix section"},
			{StartPage: 414, EndPage: 491, Reason: "Notes and Bibliography section"},
			{StartPage: 492, EndPage: 503, Reason: "Index section"},
		},
	}

	sanitized := sanitizeExcludedRanges(503, pattern.Excluded)
	if len(sanitized) != 3 {
		t.Fatalf("sanitizeExcludedRanges retained %d ranges, want 3: %#v", len(sanitized), sanitized)
	}
	if got := deriveBackMatterStart(503, pattern); got != 412 {
		t.Fatalf("deriveBackMatterStart = %d, want 412", got)
	}
}

func TestCreateLinkTocWorkUnitsCapsActiveEntries(t *testing.T) {
	entries := make([]*toc_entry_finder.TocEntry, maxConcurrentLinkTocEntries+3)
	for i := range entries {
		entries[i] = &toc_entry_finder.TocEntry{
			DocID:             "entry-" + string(rune('a'+i)),
			EntryNumber:       string(rune('1' + i)),
			LevelName:         "chapter",
			Title:             "Chapter",
			PrintedPageNumber: "1",
			SortOrder:         (i + 1) * 100,
		}
	}

	j, _ := newTocRecoveryJob(entries)
	j.Book.TotalPages = 100

	units := j.CreateLinkTocWorkUnits(context.Background())
	if len(units) != maxConcurrentLinkTocEntries {
		t.Fatalf("created %d initial link units, want cap %d", len(units), maxConcurrentLinkTocEntries)
	}
	if len(j.LinkTocEntryAgents) != maxConcurrentLinkTocEntries {
		t.Fatalf("active agents = %d, want %d", len(j.LinkTocEntryAgents), maxConcurrentLinkTocEntries)
	}
	total, done := j.Book.GetTocLinkProgress()
	if total != len(entries) || done != 0 {
		t.Fatalf("link progress = %d/%d, want 0/%d", done, total, len(entries))
	}
}

func TestAppendLinkTocRetryHintAccumulatesRejectionReasons(t *testing.T) {
	hint := appendLinkTocRetryHint("", 0, fmt.Errorf(`agent returned scan_page 93 for "PLANNING \"TORCH\"" without matching OCR evidence`))
	if !strings.Contains(hint, "Attempt 1 rejected") || !strings.Contains(hint, "scan_page 93") {
		t.Fatalf("unexpected first retry hint: %q", hint)
	}

	hint = appendLinkTocRetryHint(hint, 1, fmt.Errorf(`agent returned scan_page 98 for "PLANNING \"TORCH\"" without matching OCR evidence`))
	if !strings.Contains(hint, "Attempt 1 rejected") || !strings.Contains(hint, "Attempt 2 rejected") {
		t.Fatalf("hint did not preserve accumulated attempts: %q", hint)
	}
	if !strings.Contains(hint, "scan_page 93") || !strings.Contains(hint, "scan_page 98") {
		t.Fatalf("hint missing rejected pages: %q", hint)
	}
}

func TestConvertLinkTocAgentUnitsPreservesRetryMetadata(t *testing.T) {
	j, _ := newTocRecoveryJob(nil)
	retryHint := "Attempt 1 rejected: agent did not complete within 25 iterations"

	units := j.convertLinkTocAgentUnits([]agent.WorkUnit{{
		Type:        agent.WorkUnitTypeLLM,
		ChatRequest: &providers.ChatRequest{},
	}}, "entry-1", 2, retryHint)
	if len(units) != 1 {
		t.Fatalf("converted %d units, want 1", len(units))
	}

	info, ok := j.GetWorkUnit(units[0].ID)
	if !ok {
		t.Fatalf("converted unit was not registered")
	}
	if info.UnitType != WorkUnitTypeLinkToc || info.EntryDocID != "entry-1" {
		t.Fatalf("registered info = %#v, want link_toc entry-1", info)
	}
	if info.RetryCount != 2 || info.RetryHint != retryHint {
		t.Fatalf("retry metadata = count %d hint %q, want count 2 hint %q", info.RetryCount, info.RetryHint, retryHint)
	}
}

func TestCreateLinkTocWorkUnitsRestoresDurableRetryMetadata(t *testing.T) {
	retryHint := "Attempt 2 rejected before restart"
	entry := &toc_entry_finder.TocEntry{
		DocID:             "entry-1",
		Title:             "Stubborn chapter",
		LinkRetries:       2,
		LinkFailureReason: retryHint,
	}
	j, _ := newTocRecoveryJob([]*toc_entry_finder.TocEntry{entry})
	j.Book.TotalPages = 100

	units := j.CreateLinkTocWorkUnits(context.Background())
	if len(units) != 1 {
		t.Fatalf("created %d units, want 1", len(units))
	}
	info, ok := j.GetWorkUnit(units[0].ID)
	if !ok {
		t.Fatal("created unit was not registered")
	}
	if info.RetryCount != 2 || info.RetryHint != retryHint {
		t.Fatalf("restored retry metadata = count %d hint %q", info.RetryCount, info.RetryHint)
	}
}
