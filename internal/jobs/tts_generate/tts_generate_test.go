package tts_generate

import (
	"errors"
	"testing"
	"time"
)

func TestResolveAudioInclude(t *testing.T) {
	if !resolveAudioInclude(map[string]any{"audio_include": true}) {
		t.Fatal("expected audio_include=true to include")
	}
	if resolveAudioInclude(map[string]any{"audio_include": false}) {
		t.Fatal("expected audio_include=false to exclude")
	}
	if !resolveAudioInclude(map[string]any{"matter_type": "front_matter"}) {
		t.Fatal("expected front_matter to include by default")
	}
	if !resolveAudioInclude(map[string]any{"matter_type": "body"}) {
		t.Fatal("expected body to include by default")
	}
	if resolveAudioInclude(map[string]any{"matter_type": "back_matter"}) {
		t.Fatal("expected back_matter to exclude by default")
	}
	if !resolveAudioInclude(map[string]any{"matter_type": ""}) {
		t.Fatal("expected unknown matter_type to include by default")
	}
}

func TestNewJobFromStateSetsTotalSegmentsForExistingProgress(t *testing.T) {
	state := &AudioState{
		BookID: "book-1",
		Chapters: []*Chapter{
			{
				DocID:        "chapter-1",
				ChapterIdx:   0,
				PolishedText: "One.\n\nTwo.\n\nThree.",
			},
		},
		ChapterProgress: map[string]*ChapterProgress{
			"chapter-1": {
				ChapterDocID:      "chapter-1",
				ChapterIdx:        0,
				CompletedSegments: 1,
				Segments: map[int]*SegmentResult{
					0: &SegmentResult{DurationMS: 1000, CostUSD: 0.001},
				},
			},
		},
	}

	job := NewJobFromState(state)
	progress := job.State.ChapterProgress["chapter-1"]
	if progress == nil {
		t.Fatal("expected chapter progress to exist")
	}
	if progress.TotalSegments != 3 {
		t.Fatalf("expected TotalSegments=3, got %d", progress.TotalSegments)
	}
	if job.State.IsChapterComplete("chapter-1") {
		t.Fatal("chapter should not be complete with only 1/3 segments")
	}
}

func TestCreateConcatenateWorkUnitIncludesFormat(t *testing.T) {
	j := &Job{
		State: &AudioState{
			BookID: "book-1",
			Format: "mp3_22050_32",
		},
		Tracker: NewWorkUnitTracker(),
	}

	unit := j.createConcatenateWorkUnit("chapter-1", 4)
	data, ok := unit.CPURequest.Data.(map[string]any)
	if !ok {
		t.Fatal("expected CPURequest.Data to be a map")
	}
	if got, _ := data["format"].(string); got != "mp3_22050_32" {
		t.Fatalf("expected format=mp3_22050_32, got %q", got)
	}
}

func TestGetPreviousRequestIDsFiltersStaleAndLimitsTo3(t *testing.T) {
	now := time.Now().UTC()
	j := &Job{
		State: &AudioState{
			ChapterProgress: map[string]*ChapterProgress{
				"chapter-1": {
					RequestIDSequence: []RequestIDRef{
						{ID: "stale-1", CreatedAt: now.Add(-3 * time.Hour)},
						{ID: "fresh-1", CreatedAt: now.Add(-90 * time.Minute)},
						{ID: "fresh-2", CreatedAt: now.Add(-30 * time.Minute)},
						{ID: "fresh-3", CreatedAt: now.Add(-20 * time.Minute)},
						{ID: "fresh-4", CreatedAt: now.Add(-10 * time.Minute)},
					},
				},
			},
		},
	}

	ids := j.getPreviousRequestIDs("chapter-1")
	if len(ids) != 3 {
		t.Fatalf("expected 3 request IDs, got %d", len(ids))
	}
	if ids[0] != "fresh-2" || ids[1] != "fresh-3" || ids[2] != "fresh-4" {
		t.Fatalf("unexpected request IDs: %#v", ids)
	}
	if got := len(j.State.ChapterProgress["chapter-1"].RequestIDSequence); got != 4 {
		t.Fatalf("expected stale request to be pruned, got sequence len=%d", got)
	}
}

func TestShouldDisableRequestStitching(t *testing.T) {
	if !shouldDisableRequestStitching(errors.New("previous_request_ids should be no older than two hours")) {
		t.Fatal("expected stitching retry fallback for stale previous_request_ids error")
	}
	if shouldDisableRequestStitching(errors.New("status 500 timeout")) {
		t.Fatal("unexpected stitching fallback for unrelated error")
	}
}

func TestFormatCompatibility(t *testing.T) {
	if got := NormalizeOutputFormat(" MP3 "); got != "mp3_44100_128" {
		t.Fatalf("expected normalized mp3_44100_128, got %q", got)
	}
	if !IsStorytellerCompatibleFormat("mp3_44100_128") {
		t.Fatal("expected mp3_44100_128 to be storyteller-compatible")
	}
	if IsStorytellerCompatibleFormat("wav_44100") {
		t.Fatal("expected wav_44100 to be storyteller-incompatible")
	}
	cfg := Config{TTSProvider: "elevenlabs", Format: "wav_44100"}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected Validate to reject non-mp3 format")
	}
}
