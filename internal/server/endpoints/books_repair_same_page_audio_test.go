package endpoints

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"regexp"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

func TestRepairSamePageAudioIsTargetedAndIdempotent(t *testing.T) {
	included := map[string]bool{"chapter-1": true, "chapter-2": true, "chapter-3": true, "chapter-4": true}
	updates := 0
	docIDPattern := regexp.MustCompile(`update_Chapter\(docID: "([^"]+)"`)
	defraServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var request struct {
			Query string `json:"query"`
		}
		if err := json.Unmarshal(body, &request); err != nil {
			t.Fatalf("decode GraphQL request: %v", err)
		}
		w.Header().Set("Content-Type", "application/json")
		if match := docIDPattern.FindStringSubmatch(request.Query); len(match) == 2 {
			included[match[1]] = false
			updates++
			_, _ = fmt.Fprintf(w, `{"data":{"update_Chapter":[{"_docID":%q,"_version":{"cid":"cid-%d"}}]}}`, match[1], updates)
			return
		}
		_, _ = fmt.Fprintf(w, `{"data":{"Book":[{"_docID":"book-1","status":"complete","structure_complete":true,"structure_failed":false}],"Chapter":[
			{"_docID":"chapter-4","entry_id":"ch_004","title":"Next","start_page":14,"sort_order":400,"audio_include":%t},
			{"_docID":"chapter-2","entry_id":"ch_002","title":"Section One","start_page":10,"sort_order":200,"audio_include":%t},
			{"_docID":"chapter-1","entry_id":"ch_001","title":"Chapter","start_page":10,"sort_order":100,"audio_include":%t},
			{"_docID":"chapter-3","entry_id":"ch_003","title":"Section Two","start_page":10,"sort_order":300,"audio_include":%t}
		]}}`, included["chapter-4"], included["chapter-2"], included["chapter-1"], included["chapter-3"])
	}))
	defer defraServer.Close()

	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient: defra.NewClient(defraServer.URL),
	})
	call := func() RepairSamePageAudioResponse {
		req := httptest.NewRequest(http.MethodPost, "/api/books/book-1/repair-same-page-audio", nil).WithContext(ctx)
		req.SetPathValue("book_id", "book-1")
		w := httptest.NewRecorder()
		(&RepairSamePageAudioEndpoint{}).handler(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("status = %d; body=%s", w.Code, w.Body.String())
		}
		var response RepairSamePageAudioResponse
		if err := json.NewDecoder(w.Body).Decode(&response); err != nil {
			t.Fatal(err)
		}
		return response
	}

	first := call()
	if first.Status != "repaired" || first.Changed != 2 || len(first.Entries) != 2 {
		t.Fatalf("first response = %#v", first)
	}
	if first.Entries[0].ChapterID != "chapter-1" || first.Entries[1].ChapterID != "chapter-2" {
		t.Fatalf("changed entries = %#v", first.Entries)
	}
	if !included["chapter-3"] || !included["chapter-4"] {
		t.Fatal("retained or unrelated chapter was changed")
	}

	second := call()
	if second.Status != "unchanged" || second.Changed != 0 || updates != 2 {
		t.Fatalf("idempotent response = %#v; updates=%d", second, updates)
	}
}

func TestRepairSamePageAudioRequiresTerminalStructure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"data":{"Book":[{"_docID":"book-1","status":"processing","structure_complete":false,"structure_failed":false}],"Chapter":[]}}`)
	}))
	defer server.Close()

	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient: defra.NewClient(server.URL),
	})
	req := httptest.NewRequest(http.MethodPost, "/api/books/book-1/repair-same-page-audio", nil).WithContext(ctx)
	req.SetPathValue("book_id", "book-1")
	w := httptest.NewRecorder()
	(&RepairSamePageAudioEndpoint{}).handler(w, req)

	if w.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409; body=%s", w.Code, w.Body.String())
	}
}
