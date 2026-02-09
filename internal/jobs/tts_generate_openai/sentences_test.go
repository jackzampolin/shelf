package tts_generate_openai

import (
	"strings"
	"testing"
)

func TestSplitIntoSentences_Basic(t *testing.T) {
	text := "First sentence. Second sentence! Third sentence? Fourth."
	got := splitIntoSentences(text)
	if len(got) != 4 {
		t.Fatalf("expected 4 sentences, got %d: %#v", len(got), got)
	}
}

func TestSplitIntoSentences_AbbreviationsAndDecimals(t *testing.T) {
	text := "Mr. Smith measured 3.14 meters. Dr. Jones agreed."
	got := splitIntoSentences(text)
	if len(got) != 2 {
		t.Fatalf("expected 2 sentences, got %d: %#v", len(got), got)
	}
}

func TestSplitIntoSentences_Ellipsis(t *testing.T) {
	text := "Wait... really? Yes."
	got := splitIntoSentences(text)
	if len(got) != 2 {
		t.Fatalf("expected 2 sentences, got %d: %#v", len(got), got)
	}
	if got[0] != "Wait... really?" {
		t.Fatalf("unexpected first sentence: %q", got[0])
	}
}

func TestSplitIntoSentences_OversizedFallback(t *testing.T) {
	parts := make([]string, 0, 500)
	for i := 0; i < 1200; i++ {
		parts = append(parts, "clause")
	}
	text := strings.Join(parts, ", ") + "."
	got := splitIntoSentences(text)
	if len(got) < 2 {
		t.Fatalf("expected oversized sentence to split into multiple chunks, got %d", len(got))
	}
	for i, seg := range got {
		if len([]rune(seg)) > maxOpenAITTSChars {
			t.Fatalf("segment %d exceeds max chars: %d", i, len([]rune(seg)))
		}
	}
}

func TestSplitIntoSentences_Empty(t *testing.T) {
	got := splitIntoSentences("   \n\t ")
	if len(got) != 0 {
		t.Fatalf("expected no segments, got %#v", got)
	}
}
