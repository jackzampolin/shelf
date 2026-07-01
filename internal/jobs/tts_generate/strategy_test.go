package tts_generate

import (
	"fmt"
	"strings"
	"testing"
)

// newTestJob builds a minimal Job with one chapter and one segment.
func newTestJob(t *testing.T, jobType string) *Job {
	t.Helper()
	return newTestJobWithChapters(t, jobType, 1, 1)
}

// newTestJobWithChapters builds a Job with the given number of chapters,
// each containing segmentsPerChapter paragraphs of polished text.
func newTestJobWithChapters(t *testing.T, jobType string, chapterCount, segmentsPerChapter int) *Job {
	t.Helper()

	paragraphs := make([]string, 0, segmentsPerChapter)
	for i := 0; i < segmentsPerChapter; i++ {
		paragraphs = append(paragraphs, fmt.Sprintf("Paragraph number %d.", i))
	}

	chapters := make([]*Chapter, 0, chapterCount)
	for i := 0; i < chapterCount; i++ {
		chapters = append(chapters, &Chapter{
			DocID:        fmt.Sprintf("chapter-%d", i),
			ChapterIdx:   i,
			PolishedText: strings.Join(paragraphs, "\n\n"),
		})
	}

	j, err := NewJobFromState(jobType, &AudioState{
		BookID:   "book-test",
		Chapters: chapters,
	})
	if err != nil {
		t.Fatalf("NewJobFromState(%s): %v", jobType, err)
	}
	return j
}

func TestStrategyIdentity(t *testing.T) {
	cases := []struct {
		jobType, provider, concat string
	}{
		{JobTypeElevenLabs, "elevenlabs", "concatenate_chapter"},
		{JobTypeOpenAI, "openai", "concatenate_chapter_openai"},
	}
	for _, c := range cases {
		s, err := strategyForJobType(c.jobType)
		if err != nil {
			t.Fatalf("%s: %v", c.jobType, err)
		}
		if s.Provider() != c.provider || s.JobType() != c.jobType || s.ConcatTaskName() != c.concat {
			t.Errorf("%s: got (%s,%s,%s)", c.jobType, s.Provider(), s.JobType(), s.ConcatTaskName())
		}
	}
	if _, err := strategyForJobType("bogus"); err == nil {
		t.Error("expected error for unknown job type")
	}
}

func TestJobReportsPersistedType(t *testing.T) {
	for _, jt := range []string{JobTypeElevenLabs, JobTypeOpenAI} {
		j := newTestJob(t, jt) // helper: minimal Job with one chapter, one segment
		if j.Type() != jt {
			t.Errorf("Type() = %s, want %s", j.Type(), jt)
		}
		if m := j.MetricsFor(); m.Stage != jt {
			t.Errorf("MetricsFor().Stage = %s, want %s", m.Stage, jt)
		}
	}
}

func TestElevenLabsQueuesOneSegmentPerChapter(t *testing.T) {
	j := newTestJobWithChapters(t, JobTypeElevenLabs, 2 /*chapters*/, 3 /*segments each*/)
	units := j.strategy.InitialWorkUnits(j)
	if len(units) != 2 {
		t.Fatalf("got %d initial units, want 2 (one per chapter)", len(units))
	}
}
