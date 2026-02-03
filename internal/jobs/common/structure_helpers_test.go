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
