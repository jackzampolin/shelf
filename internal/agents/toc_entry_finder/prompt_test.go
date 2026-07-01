package toc_entry_finder

import (
	"strings"
	"testing"
)

func TestBuildUserPrompt_NonBackMatterKeepsLateContextOutOfTarget(t *testing.T) {
	entry := &TocEntry{
		EntryNumber:       "23",
		LevelName:         "chapter",
		Title:             `OPERATION "STUDY"`,
		PrintedPageNumber: "489",
	}

	prompt := BuildUserPrompt(entry, 615, &BookStructure{
		BackMatterStart:    557,
		BackMatterTypes:    "footnotes, appendices, glossary, index",
		TargetIsBackMatter: false,
	})

	if !strings.Contains(prompt, `Find only this ToC entry: "chapter 23 OPERATION \"STUDY\""`) {
		t.Fatalf("prompt missing target entry:\n%s", prompt)
	}
	if strings.Contains(prompt, `Find: "Back matter`) {
		t.Fatalf("prompt makes back matter look like target:\n%s", prompt)
	}
	if !strings.Contains(prompt, "Do not search for or return the late-section labels") {
		t.Fatalf("prompt missing late-label guard:\n%s", prompt)
	}
	if !strings.Contains(prompt, "Start near scan pages 499-524") {
		t.Fatalf("prompt missing expected scan-page range:\n%s", prompt)
	}
	if !strings.Contains(prompt, "If grep_text shows a dense title cluster") {
		t.Fatalf("prompt missing cluster decision rule:\n%s", prompt)
	}
}

func TestBuildUserPrompt_BackMatterTargetAllowsLatePages(t *testing.T) {
	entry := &TocEntry{
		LevelName:         "section",
		Title:             "GLOSSARY OF MILITARY CODE NAMES",
		PrintedPageNumber: "556",
	}

	prompt := BuildUserPrompt(entry, 615, &BookStructure{
		BackMatterStart:    557,
		BackMatterTypes:    "footnotes, appendices, glossary, index",
		TargetIsBackMatter: true,
	})

	if !strings.Contains(prompt, "This target is a late/back-matter ToC entry") {
		t.Fatalf("prompt should allow late pages for back-matter target:\n%s", prompt)
	}
	if strings.Contains(prompt, "For this non-back-matter target") {
		t.Fatalf("prompt used non-back-matter warning for back-matter target:\n%s", prompt)
	}
}

func TestBuildUserPrompt_IncludesRetryFeedback(t *testing.T) {
	entry := &TocEntry{
		EntryNumber:       "5",
		LevelName:         "chapter",
		Title:             `PLANNING "TORCH"`,
		PrintedPageNumber: "83",
	}

	prompt := BuildUserPrompt(entry, 615, &BookStructure{
		RetryHint: `Attempt 1 rejected: agent returned scan_page 93 for "PLANNING \"TORCH\"" without matching OCR evidence`,
	})

	if !strings.Contains(prompt, "PREVIOUS REJECTION FEEDBACK") {
		t.Fatalf("prompt missing retry feedback section:\n%s", prompt)
	}
	if !strings.Contains(prompt, "scan_page 93") {
		t.Fatalf("prompt missing rejected scan page:\n%s", prompt)
	}
	if !strings.Contains(prompt, "Do not repeat a rejected scan_page") {
		t.Fatalf("prompt missing retry behavior instruction:\n%s", prompt)
	}
}
