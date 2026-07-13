package extract_toc

import "testing"

func TestCreateWorkUnitAllowsLargeStructuredToc(t *testing.T) {
	unit := CreateWorkUnit(Input{ToCPages: []ToCPage{{PageNum: 1, OCRText: "Contents"}}})
	if unit.ChatRequest == nil {
		t.Fatal("CreateWorkUnit returned no chat request")
	}
	if got := unit.ChatRequest.MaxTokens; got != 32768 {
		t.Fatalf("MaxTokens = %d, want 32768", got)
	}
}
