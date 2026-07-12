package job

import (
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestCoalesceSharedStartPageAudioKeepsLastIncludedEntry(t *testing.T) {
	chapters := []*common.ChapterState{
		{Title: "Chapter Ten", StartPage: 100, AudioInclude: true},
		{Title: "First Section", StartPage: 100, AudioInclude: true},
		{Title: "Second Section", StartPage: 100, AudioInclude: true},
		{Title: "Next Chapter", StartPage: 104, AudioInclude: true},
	}

	if got := coalesceSharedStartPageAudio(chapters); got != 2 {
		t.Fatalf("excluded = %d, want 2", got)
	}
	if chapters[0].AudioInclude || chapters[1].AudioInclude {
		t.Fatal("earlier same-page entries remained included")
	}
	if !chapters[2].AudioInclude || !chapters[3].AudioInclude {
		t.Fatal("retained or unrelated entry was excluded")
	}
	if !strings.Contains(chapters[0].AudioIncludeReasoning, `under "Second Section"`) {
		t.Fatalf("reasoning does not identify retained entry: %q", chapters[0].AudioIncludeReasoning)
	}
}

func TestCoalesceSharedStartPageAudioPreservesModelExclusions(t *testing.T) {
	chapters := []*common.ChapterState{
		{Title: "Body Tail", StartPage: 200, AudioInclude: true},
		{Title: "Index", StartPage: 200, AudioInclude: false, AudioIncludeReasoning: "Index"},
		{Title: "Back Cover", StartPage: 201, AudioInclude: false, AudioIncludeReasoning: "Cover"},
	}

	if got := coalesceSharedStartPageAudio(chapters); got != 0 {
		t.Fatalf("excluded = %d, want 0", got)
	}
	if !chapters[0].AudioInclude {
		t.Fatal("only model-included entry on a shared page was excluded")
	}
	if chapters[1].AudioInclude || chapters[1].AudioIncludeReasoning != "Index" {
		t.Fatal("model-excluded entry was changed")
	}
}

func TestCoalesceSharedStartPageAudioLeavesDistinctPagesAlone(t *testing.T) {
	chapters := []*common.ChapterState{
		{Title: "One", StartPage: 1, AudioInclude: true},
		nil,
		{Title: "Two", StartPage: 2, AudioInclude: true},
	}

	if got := coalesceSharedStartPageAudio(chapters); got != 0 {
		t.Fatalf("excluded = %d, want 0", got)
	}
	if !chapters[0].AudioInclude || !chapters[2].AudioInclude {
		t.Fatal("distinct-page entries were changed")
	}
}
