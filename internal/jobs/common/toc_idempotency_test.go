package common

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

func TestSaveTocExtractResultRecoversExistingDocIDCollision(t *testing.T) {
	var mu sync.Mutex
	requests := make([]string, 0, 4)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Query string `json:"query"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		mu.Lock()
		requests = append(requests, body.Query)
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")

		switch {
		case strings.Contains(body.Query, "upsert_TocEntry"):
			w.Write([]byte(`{"errors":[{"message":"a document with the given ID already exists. DocID: bae-collision"}]}`))
		case strings.Contains(body.Query, "TocEntry(filter"):
			w.Write([]byte(`{"data":{"TocEntry":[{"_docID":"entry-existing","sort_order":0,"unique_key":"toc-1:0:old"}]}}`))
		case strings.Contains(body.Query, "update_TocEntry"):
			if !strings.Contains(body.Query, `docID: "entry-existing"`) {
				t.Fatalf("updated wrong ToC entry: %s", body.Query)
			}
			if !strings.Contains(body.Query, `unique_key: "toc-1:0"`) {
				t.Fatalf("stable unique key not restored: %s", body.Query)
			}
			w.Write([]byte(`{"data":{"update_TocEntry":[{"_docID":"entry-existing","_version":[{"cid":"entry-cid"}]}]}}`))
		case strings.Contains(body.Query, "update_ToC"):
			w.Write([]byte(`{"data":{"update_ToC":[{"_docID":"toc-1","_version":[{"cid":"toc-cid"}]}]}}`))
		default:
			t.Fatalf("unexpected query: %s", body.Query)
		}
	}))
	defer server.Close()

	client := defra.NewClient(server.URL)
	sink := defra.NewSink(defra.SinkConfig{
		Client:        client,
		BatchSize:     1,
		FlushInterval: time.Millisecond,
		Concurrency:   1,
	})
	sinkCtx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sink.Start(sinkCtx)
	defer sink.Stop()

	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient: client,
		DefraSink:   sink,
	})
	cid, err := SaveTocExtractResult(ctx, "toc-1", &extract_toc.Result{
		Entries: []extract_toc.Entry{{Title: "Chapter One", Level: 1}},
	})
	if err != nil {
		t.Fatalf("SaveTocExtractResult: %v", err)
	}
	if cid != "toc-cid" {
		t.Fatalf("CID = %q, want toc-cid", cid)
	}

	mu.Lock()
	defer mu.Unlock()
	if len(requests) != 4 {
		t.Fatalf("requests = %d, want 4: %#v", len(requests), requests)
	}
}
