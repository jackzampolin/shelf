package endpoints

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

func TestGetBookChaptersBatchesAndGroupsParagraphs(t *testing.T) {
	var paragraphQueries int
	var paragraphQuery string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request struct {
			Query string `json:"query"`
		}
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Errorf("decode GraphQL request: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.Contains(request.Query, "Book(docID:"):
			_, _ = io.WriteString(w, `{"data":{"Book":[{"_docID":"book-1","title":"Book","page_count":12}]}}`)
		case strings.Contains(request.Query, "Chapter(filter:"):
			_, _ = io.WriteString(w, `{"data":{"Chapter":[
				{"_docID":"chapter-2","title":"Second","start_page":6,"end_page":12,"sort_order":20},
				{"_docID":"chapter-1","title":"First","start_page":1,"end_page":5,"sort_order":10}
			]}}`)
		case strings.Contains(request.Query, "Paragraph(filter:"):
			paragraphQueries++
			paragraphQuery = request.Query
			_, _ = io.WriteString(w, `{"data":{"Paragraph":[
				{"_docID":"paragraph-2b","_chapterID":"chapter-2","sort_order":2,"start_page":7,"polished_text":"Second B"},
				{"_docID":"paragraph-1b","_chapterID":"chapter-1","sort_order":2,"start_page":2,"polished_text":"First B"},
				{"_docID":"paragraph-1a","_chapterID":"chapter-1","sort_order":1,"start_page":1,"polished_text":"First A"},
				{"_docID":"paragraph-2a","_chapterID":"chapter-2","sort_order":1,"start_page":6,"polished_text":"Second A"}
			]}}`)
		default:
			t.Errorf("unexpected GraphQL query: %s", request.Query)
			w.WriteHeader(http.StatusBadRequest)
		}
	}))
	defer server.Close()

	response := callBookChapters(t, server.URL, "?include_paragraphs=true")
	if paragraphQueries != 1 {
		t.Fatalf("paragraph queries = %d, want 1", paragraphQueries)
	}
	if !strings.Contains(paragraphQuery, `_chapterID: {_in: ["chapter-1", "chapter-2"]}`) {
		t.Fatalf("paragraph query does not batch chapter IDs: %s", paragraphQuery)
	}
	if len(response.Chapters) != 2 || response.Chapters[0].ID != "chapter-1" || response.Chapters[1].ID != "chapter-2" {
		t.Fatalf("chapters not canonically ordered: %#v", response.Chapters)
	}
	for _, chapter := range response.Chapters {
		if len(chapter.Paragraphs) != 2 {
			t.Fatalf("chapter %s paragraphs = %#v", chapter.ID, chapter.Paragraphs)
		}
		if chapter.Paragraphs[0].SortOrder != 1 || chapter.Paragraphs[1].SortOrder != 2 {
			t.Fatalf("chapter %s paragraphs not canonically ordered: %#v", chapter.ID, chapter.Paragraphs)
		}
	}
	if response.Chapters[0].Paragraphs[0].ID != "paragraph-1a" || response.Chapters[0].Paragraphs[1].ID != "paragraph-1b" {
		t.Fatalf("paragraphs assigned to wrong first chapter: %#v", response.Chapters[0].Paragraphs)
	}
	if response.Chapters[1].Paragraphs[0].ID != "paragraph-2a" || response.Chapters[1].Paragraphs[1].ID != "paragraph-2b" {
		t.Fatalf("paragraphs assigned to wrong second chapter: %#v", response.Chapters[1].Paragraphs)
	}
}

func TestGetBookChaptersPropagatesRequestedExpansionErrors(t *testing.T) {
	tests := []struct {
		name       string
		query      string
		failureFor string
		status     int
		body       string
		wantError  string
	}{
		{
			name:       "book GraphQL error",
			failureFor: "Book(docID:",
			status:     http.StatusOK,
			body:       `{"errors":[{"message":"book query failed"}]}`,
			wantError:  "book query failed",
		},
		{
			name:       "chapter GraphQL error",
			failureFor: "Chapter(filter:",
			status:     http.StatusOK,
			body:       `{"errors":[{"message":"chapter query failed"}]}`,
			wantError:  "chapter query failed",
		},
		{
			name:       "page GraphQL error",
			query:      "?include_text=true",
			failureFor: "Page(filter:",
			status:     http.StatusOK,
			body:       `{"errors":[{"message":"page expansion failed"}]}`,
			wantError:  "page expansion failed",
		},
		{
			name:       "paragraph GraphQL error",
			query:      "?include_paragraphs=true",
			failureFor: "Paragraph(filter:",
			status:     http.StatusOK,
			body:       `{"errors":[{"message":"paragraph expansion failed"}]}`,
			wantError:  "paragraph expansion failed",
		},
		{
			name:       "paragraph transport error",
			query:      "?include_paragraphs=true",
			failureFor: "Paragraph(filter:",
			status:     http.StatusInternalServerError,
			body:       "defra unavailable",
			wantError:  "defra server error",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var request struct {
					Query string `json:"query"`
				}
				if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
					t.Errorf("decode GraphQL request: %v", err)
					w.WriteHeader(http.StatusBadRequest)
					return
				}
				w.Header().Set("Content-Type", "application/json")
				switch {
				case strings.Contains(request.Query, tt.failureFor):
					w.WriteHeader(tt.status)
					_, _ = io.WriteString(w, tt.body)
				case strings.Contains(request.Query, "Book(docID:"):
					_, _ = io.WriteString(w, `{"data":{"Book":[{"_docID":"book-1","title":"Book","page_count":12}]}}`)
				case strings.Contains(request.Query, "Chapter(filter:"):
					_, _ = io.WriteString(w, `{"data":{"Chapter":[{"_docID":"chapter-1","title":"First","start_page":1,"end_page":5,"sort_order":10}]}}`)
				default:
					t.Errorf("unexpected GraphQL query: %s", request.Query)
					w.WriteHeader(http.StatusBadRequest)
				}
			}))
			defer server.Close()

			ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
				DefraClient: defra.NewClient(server.URL),
			})
			req := httptest.NewRequest(http.MethodGet, "/api/books/book-1/chapters"+tt.query, nil).WithContext(ctx)
			req.SetPathValue("id", "book-1")
			w := httptest.NewRecorder()
			(&GetBookChaptersEndpoint{}).handler(w, req)

			if w.Code != http.StatusInternalServerError {
				t.Fatalf("status = %d, want 500; body=%s", w.Code, w.Body.String())
			}
			if !strings.Contains(w.Body.String(), tt.wantError) {
				t.Fatalf("body = %q, want error containing %q", w.Body.String(), tt.wantError)
			}
		})
	}
}

func callBookChapters(t *testing.T, defraURL, query string) ChaptersResponse {
	t.Helper()
	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient: defra.NewClient(defraURL),
	})
	req := httptest.NewRequest(http.MethodGet, "/api/books/book-1/chapters"+query, nil).WithContext(ctx)
	req.SetPathValue("id", "book-1")
	w := httptest.NewRecorder()
	(&GetBookChaptersEndpoint{}).handler(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d; body=%s", w.Code, w.Body.String())
	}
	var response ChaptersResponse
	if err := json.NewDecoder(w.Body).Decode(&response); err != nil {
		t.Fatal(err)
	}
	return response
}
