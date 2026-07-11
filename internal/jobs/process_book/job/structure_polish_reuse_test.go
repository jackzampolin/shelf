package job

import (
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestReuseUnchangedPolishByStableTocIdentity(t *testing.T) {
	prior := []*common.ChapterState{
		{
			EntryID:          "ch_002",
			TocEntryID:       "toc-stable",
			MechanicalText:   "same source text",
			PolishedText:     "Same source text.",
			EditsAppliedJSON: "[]",
			WordCount:        3,
			ExtractDone:      true,
			PolishDone:       true,
			AudioInclude:     true,
		},
	}
	current := []*common.ChapterState{
		{
			EntryID:        "ch_003", // insertion shifted the display ID
			TocEntryID:     "toc-stable",
			MechanicalText: "same source text",
			ExtractDone:    true,
		},
	}

	if got := reuseUnchangedPolish(current, prior); got != 1 {
		t.Fatalf("reused = %d, want 1", got)
	}
	if !current[0].PolishDone || current[0].PolishedText != "Same source text." {
		t.Fatalf("polish was not reused: %+v", current[0])
	}
	if current[0].WordCount != 3 {
		t.Fatalf("word count = %d, want 3", current[0].WordCount)
	}
}

func TestReuseUnchangedPolishFailsClosed(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*common.ChapterState)
	}{
		{"changed source", func(ch *common.ChapterState) { ch.MechanicalText = "changed" }},
		{"failed polish", func(ch *common.ChapterState) { ch.PolishFailed = true }},
		{"incomplete polish", func(ch *common.ChapterState) { ch.PolishDone = false }},
		{"formerly non-audio", func(ch *common.ChapterState) { ch.AudioInclude = false }},
		{"missing polished text", func(ch *common.ChapterState) { ch.PolishedText = "" }},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			old := &common.ChapterState{
				TocEntryID:     "toc-1",
				MechanicalText: "source",
				PolishedText:   "Source.",
				ExtractDone:    true,
				PolishDone:     true,
				AudioInclude:   true,
			}
			tt.mutate(old)
			current := &common.ChapterState{
				TocEntryID:     "toc-1",
				MechanicalText: "source",
				ExtractDone:    true,
			}
			if got := reuseUnchangedPolish([]*common.ChapterState{current}, []*common.ChapterState{old}); got != 0 {
				t.Fatalf("reused = %d, want 0", got)
			}
			if current.PolishDone {
				t.Fatal("unsafe polish was reused")
			}
		})
	}
}

func TestReuseUnchangedPolishRejectsAmbiguousIdentity(t *testing.T) {
	prior := []*common.ChapterState{
		{TocEntryID: "toc-1", MechanicalText: "source", PolishedText: "One", ExtractDone: true, PolishDone: true, AudioInclude: true},
		{TocEntryID: "toc-1", MechanicalText: "source", PolishedText: "Two", ExtractDone: true, PolishDone: true, AudioInclude: true},
	}
	current := []*common.ChapterState{{TocEntryID: "toc-1", MechanicalText: "source", ExtractDone: true}}
	if got := reuseUnchangedPolish(current, prior); got != 0 {
		t.Fatalf("reused = %d, want 0", got)
	}
}

func TestChapterExtractUpdateClearsOnlyStalePolish(t *testing.T) {
	unpolished := chapterExtractUpdate(&common.ChapterState{
		MechanicalText: "new source",
		WordCount:      2,
	})
	if unpolished["polish_complete"] != false || unpolished["polished_text"] != "" {
		t.Fatalf("stale polish was not cleared: %+v", unpolished)
	}

	reused := chapterExtractUpdate(&common.ChapterState{
		MechanicalText: "same source",
		PolishedText:   "Same source.",
		PolishDone:     true,
		WordCount:      2,
	})
	if _, ok := reused["polish_complete"]; ok {
		t.Fatalf("reused polish was overwritten: %+v", reused)
	}
}
