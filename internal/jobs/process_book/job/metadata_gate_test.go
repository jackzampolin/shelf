package job

import (
	"context"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestMetadataWaitsForCompleteFrontMatterPrefix(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})
	book := common.NewBookState("book-1")
	book.Store = store
	book.TotalPages = OcrThresholdForMetadata + 1
	book.OcrProviders = []string{"chandra-local"}
	book.MetadataProvider = "qwen-local"
	book.EnableMetadata = true

	for pageNum := 1; pageNum < OcrThresholdForMetadata; pageNum++ {
		page := book.GetOrCreatePage(pageNum)
		page.MarkOcrComplete("chandra-local", "front matter")
		page.SetOcrMarkdown("front matter")
	}
	// Keep page 20 incomplete but complete page 21. The old count-based gate
	// incorrectly started metadata here because twenty total pages were done.
	later := book.GetOrCreatePage(OcrThresholdForMetadata + 1)
	later.MarkOcrComplete("chandra-local", "later page")
	later.SetOcrMarkdown("later page")

	j := NewFromLoadResult(&common.LoadBookResult{Book: book})
	if units := j.MaybeStartBookOperations(context.Background()); len(units) != 0 {
		t.Fatalf("metadata started with a front-matter hole; units=%d", len(units))
	}
	if book.MetadataIsStarted() {
		t.Fatal("metadata state started with page 20 incomplete")
	}

	missing := book.GetOrCreatePage(OcrThresholdForMetadata)
	missing.MarkOcrComplete("chandra-local", "repaired page")
	missing.SetOcrMarkdown("repaired page")
	units := j.MaybeStartBookOperations(context.Background())
	if len(units) != 1 || !book.MetadataIsStarted() {
		t.Fatalf("metadata did not start after prefix repair; units=%d started=%v", len(units), book.MetadataIsStarted())
	}
}
