package metadata

import "testing"

func TestCreateWorkUnitAllowsReasoningBeforeMetadataJSON(t *testing.T) {
	unit := CreateWorkUnit(Input{BookText: "title page"})
	if unit.ChatRequest == nil {
		t.Fatal("CreateWorkUnit returned no chat request")
	}
	if got, want := unit.ChatRequest.MaxTokens, 4096; got != want {
		t.Fatalf("MaxTokens = %d, want %d", got, want)
	}
}
