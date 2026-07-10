package common

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

func TestLoadPageStatesPaginatesLargeBooks(t *testing.T) {
	const totalPages = 205
	offsetPattern := regexp.MustCompile(`offset: (\d+)`)
	pageIDPattern := regexp.MustCompile(`"page-(\d+)"`)
	var (
		mu            sync.Mutex
		offsets       []int
		ocrBatchCalls int
	)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v0/graphql" {
			http.NotFound(w, r)
			return
		}
		var req defra.GQLRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		if strings.Contains(req.Query, "OcrResult(") {
			matches := pageIDPattern.FindAllStringSubmatch(req.Query, -1)
			results := make([]map[string]any, 0, len(matches))
			for _, match := range matches {
				pageNum, err := strconv.Atoi(match[1])
				if err != nil {
					t.Error(err)
					continue
				}
				results = append(results, map[string]any{
					"_pageID":  fmt.Sprintf("page-%d", pageNum),
					"provider": "chandra-local",
					"text":     fmt.Sprintf("OCR page %d", pageNum),
				})
			}
			mu.Lock()
			ocrBatchCalls++
			mu.Unlock()
			w.Header().Set("Content-Type", "application/json")
			if err := json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{"OcrResult": results}}); err != nil {
				t.Error(err)
			}
			return
		}
		if !strings.Contains(req.Query, "order: {page_num: ASC}") ||
			!strings.Contains(req.Query, fmt.Sprintf("limit: %d", loadPageStatesBatchSize)) {
			http.Error(w, "page query is not stably bounded", http.StatusBadRequest)
			return
		}
		match := offsetPattern.FindStringSubmatch(req.Query)
		if len(match) != 2 {
			http.Error(w, "missing offset", http.StatusBadRequest)
			return
		}
		offset, err := strconv.Atoi(match[1])
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		mu.Lock()
		offsets = append(offsets, offset)
		mu.Unlock()

		end := min(offset+loadPageStatesBatchSize, totalPages)
		pages := make([]map[string]any, 0, end-offset)
		for pageNum := offset + 1; pageNum <= end; pageNum++ {
			pages = append(pages, map[string]any{
				"_docID":           fmt.Sprintf("page-%d", pageNum),
				"page_num":         pageNum,
				"extract_complete": true,
				"ocr_complete":     true,
			})
		}
		w.Header().Set("Content-Type", "application/json")
		if err := json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{"Page": pages}}); err != nil {
			t.Error(err)
		}
	}))
	defer server.Close()

	book := NewBookState("book-1")
	book.OcrProviders = []string{"chandra-local"}
	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient: defra.NewClient(server.URL),
	})

	if err := LoadPageStates(ctx, book); err != nil {
		t.Fatalf("LoadPageStates: %v", err)
	}
	if got := book.CountPages(); got != totalPages {
		t.Fatalf("loaded pages = %d, want %d", got, totalPages)
	}
	if got := fmt.Sprint(offsets); got != "[0 100 200]" {
		t.Fatalf("query offsets = %s, want [0 100 200]", got)
	}
	if ocrBatchCalls != 3 {
		t.Fatalf("OCR batch queries = %d, want 3", ocrBatchCalls)
	}
	last := book.GetPage(totalPages)
	if last == nil || last.GetPageDocID() != "page-205" {
		t.Fatalf("last page = %#v, want page-205", last)
	}
	if text, ok := last.GetOcrResult("chandra-local"); !ok || text != "OCR page 205" {
		t.Fatalf("last page OCR = %q, %v; want OCR page 205", text, ok)
	}
}
