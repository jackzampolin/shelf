package common

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestBuildClassifyPromptIncludesContext(t *testing.T) {
	chapter := &ChapterState{
		EntryID:        "ch-1",
		Title:          "Preface",
		StartPage:      1,
		EndPage:        2,
		Level:          1,
		LevelName:      "Chapter",
		WordCount:      123,
		MechanicalText: "This is some sample text for the preface section.",
	}

	prompt := BuildClassifyPrompt([]*ChapterState{chapter}, 200)

	if !strings.Contains(prompt, "Total pages in book: 200") {
		t.Fatalf("prompt missing total pages: %s", prompt)
	}
	if !strings.Contains(prompt, "level 1 Chapter, word_count 123") {
		t.Fatalf("prompt missing level/word_count: %s", prompt)
	}
	if !strings.Contains(prompt, "[id: ch-1]") {
		t.Fatalf("prompt missing entry id: %s", prompt)
	}
	if !strings.Contains(prompt, "text: This is some sample text") {
		t.Fatalf("prompt missing text snippet: %s", prompt)
	}
}

func TestBuildClassifyPromptFlagsReferenceAppendixSignals(t *testing.T) {
	chapter := &ChapterState{
		EntryID:   "ch-appendix",
		Title:     "Appendix B: Order of Battle",
		StartPage: 560,
		EndPage:   590,
		Level:     1,
		LevelName: "appendix",
		MechanicalText: strings.Join([]string{
			"1. Headquarters",
			"2. First Army",
			"3. Second Army",
			"4. Division Roster",
			"5. Supporting Units",
		}, "\n"),
	}

	prompt := BuildClassifyPrompt([]*ChapterState{chapter}, 615)
	for _, want := range []string{
		"content_signals:",
		"keyword:order of battle",
		"keyword:roster",
		"many_short_lines:5/5",
		"list_like_lines:5/5",
		"1. Headquarters | 2. First Army",
	} {
		if !strings.Contains(prompt, want) {
			t.Fatalf("prompt missing %q:\n%s", want, prompt)
		}
	}
	if !strings.Contains(ClassifySystemPrompt, "orders of battle") {
		t.Fatal("system prompt should explicitly exclude order-of-battle reference appendices")
	}
}

func TestClassifyResultUnmarshal(t *testing.T) {
	payload := []byte(`{
		"classifications": {"ch1": "front_matter"},
		"content_types": {"ch1": "preface"},
		"audio_include": {"ch1": true},
		"reasoning": {"ch1": "Preface should be read aloud."}
	}`)

	var result ClassifyResult
	if err := json.Unmarshal(payload, &result); err != nil {
		t.Fatalf("failed to unmarshal classify result: %v", err)
	}
	if result.Classifications["ch1"] != "front_matter" {
		t.Fatalf("classifications mismatch: %v", result.Classifications)
	}
	if result.ContentTypes["ch1"] != "preface" {
		t.Fatalf("content_types mismatch: %v", result.ContentTypes)
	}
	if !result.AudioInclude["ch1"] {
		t.Fatalf("audio_include mismatch: %v", result.AudioInclude)
	}
	if result.Reasoning["ch1"] == "" {
		t.Fatalf("reasoning missing: %v", result.Reasoning)
	}
}

func TestStripHeaderFooter(t *testing.T) {
	text := "My Header\nLine one\nLine two\nPage Footer"
	cleaned := StripHeaderFooter(text, "my header", "page footer")

	if strings.Contains(cleaned, "My Header") {
		t.Fatalf("header not stripped: %s", cleaned)
	}
	if strings.Contains(cleaned, "Page Footer") {
		t.Fatalf("footer not stripped: %s", cleaned)
	}
	if !strings.Contains(cleaned, "Line one") || !strings.Contains(cleaned, "Line two") {
		t.Fatalf("content missing after strip: %s", cleaned)
	}
}

func TestBuildPolishPromptIncludesLongChapterText(t *testing.T) {
	longText := strings.Repeat("A long OCR paragraph with enough text to review. ", 500)
	chapter := &ChapterState{Title: "Long Chapter", MechanicalText: longText}

	prompt := BuildPolishPrompt(chapter)
	if !strings.Contains(prompt, longText) {
		t.Fatal("polish prompt truncated chapter text below the configured long-chapter window")
	}
	if strings.Contains(prompt, "[... text truncated for length ...]") {
		t.Fatal("polish prompt unexpectedly marked normal long chapter as truncated")
	}
}
