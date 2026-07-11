package common

import (
	"strings"
	"testing"
)

func TestPolishMaxOutputTokensScalesAndBounds(t *testing.T) {
	if got := PolishMaxOutputTokens("short chapter"); got != minPolishOutputTokens {
		t.Fatalf("short chapter tokens = %d, want %d", got, minPolishOutputTokens)
	}
	mid := PolishMaxOutputTokens(strings.Repeat("x", 20_000))
	if mid <= minPolishOutputTokens || mid >= MaxPolishOutputTokens {
		t.Fatalf("mid-size chapter tokens = %d, want strictly bounded scaling", mid)
	}
	if got := PolishMaxOutputTokens(strings.Repeat("x", MaxPolishPromptChars*2)); got != MaxPolishOutputTokens {
		t.Fatalf("long chapter tokens = %d, want %d", got, MaxPolishOutputTokens)
	}
}
