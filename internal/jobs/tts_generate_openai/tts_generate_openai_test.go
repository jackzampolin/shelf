package tts_generate_openai

import "testing"

func TestFormatCompatibility(t *testing.T) {
	if got := NormalizeOutputFormat(" MP3_44100_128 "); got != "mp3" {
		t.Fatalf("expected normalized mp3, got %q", got)
	}
	if !IsStorytellerCompatibleFormat("mp3") {
		t.Fatal("expected mp3 to be storyteller-compatible")
	}
	if IsStorytellerCompatibleFormat("wav") {
		t.Fatal("expected wav to be storyteller-incompatible")
	}
	cfg := Config{TTSProvider: "openai", Format: "wav"}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected Validate to reject non-mp3 format")
	}
}

func TestConfigValidateProvider(t *testing.T) {
	cfg := Config{TTSProvider: "elevenlabs"}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected provider validation error for openai job")
	}
}

func TestCreateTTSWorkUnitIncludesInstructions(t *testing.T) {
	j := &Job{
		State: &AudioState{
			BookID:       "book-1",
			TTSProvider:  "openai",
			Voice:        "onyx",
			Format:       "mp3",
			Instructions: "Narrate like an audiobook",
		},
		Tracker: NewWorkUnitTracker(),
	}

	ch := &Chapter{DocID: "chapter-1", ChapterIdx: 0}
	unit := j.createTTSWorkUnit(ch, 2, "Hello world.")
	if unit.TTSRequest == nil {
		t.Fatal("expected TTSRequest")
	}
	if unit.TTSRequest.Instructions != "Narrate like an audiobook" {
		t.Fatalf("expected instructions to be propagated, got %q", unit.TTSRequest.Instructions)
	}
	if unit.TTSRequest.PreviousRequestIDs != nil {
		t.Fatalf("expected no previous request IDs for openai job, got %#v", unit.TTSRequest.PreviousRequestIDs)
	}
}
