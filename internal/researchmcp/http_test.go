package researchmcp

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func fakeShelf(t *testing.T) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/api/books", func(http.ResponseWriter, *http.Request) {
		t.Fatal("research MCP must use the existing point book endpoint")
	})
	mux.HandleFunc("/api/books/book-1", func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(book{
			ID: "book-1", Title: "A History", Author: "A. Historian", Status: "complete",
			SourceSHA256: "source-abc", StructureComplete: true,
		})
	})
	mux.HandleFunc("/api/books/book-1/chapters", func(w http.ResponseWriter, r *http.Request) {
		if got := r.URL.Query().Get("include_paragraphs"); got != "true" {
			t.Fatalf("include_paragraphs = %q", got)
		}
		_ = json.NewEncoder(w).Encode(chaptersResponse{
			Chapters: []chapter{{
				ID: "chapter-1", Title: "Origins", MatterType: "body", SortOrder: 1,
				StartPage: 10, EndPage: 12, PolishComplete: true,
				Paragraphs: []paragraph{{
					ID: "paragraph-1", SortOrder: 1, StartPage: 10,
					PolishedText: "The Marshall Plan linked European recovery to American economic power.",
				}},
			}},
		})
	})
	return httptest.NewServer(mux)
}

func TestResearchToolsPinSearchReadAndValidate(t *testing.T) {
	upstream := fakeShelf(t)
	defer upstream.Close()
	client := NewClient(upstream.URL, upstream.Client())
	ctx := context.Background()

	_, bookOut, err := client.getBook(ctx, nil, GetBookInput{BookID: "book-1"})
	if err != nil {
		t.Fatal(err)
	}
	if !bookOut.ResearchReady || bookOut.StructureDigest == "" {
		t.Fatalf("unexpected book output: %#v", bookOut)
	}
	const v1Digest = "sha256:704ab7e103614bcbcf2c9e0a2e892ef1278c6676b09cd53a60b76cb1d4f6a03c"
	if bookOut.StructureDigest != v1Digest {
		t.Fatalf("structure digest = %q, want frozen v1 digest %q", bookOut.StructureDigest, v1Digest)
	}

	_, searchOut, err := client.searchPassages(ctx, nil, SearchPassagesInput{
		BookID: "book-1", Query: "marshall plan", TopK: 5,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(searchOut.Matches) != 1 || searchOut.Matches[0].ParagraphID != "paragraph-1" {
		t.Fatalf("unexpected matches: %#v", searchOut.Matches)
	}
	_, emptySearch, err := client.searchPassages(ctx, nil, SearchPassagesInput{BookID: "book-1", Query: "absent"})
	if err != nil || emptySearch.Matches == nil {
		t.Fatalf("empty matches must encode as an empty array: %#v, %v", emptySearch.Matches, err)
	}

	match := searchOut.Matches[0]
	_, readOut, err := client.readPassage(ctx, nil, ReadPassageInput{
		BookID: "book-1", ChapterID: match.ChapterID, ParagraphID: match.ParagraphID,
		StartChar: match.StartChar, ContextBefore: 5, MaxChars: 40,
	})
	if err != nil {
		t.Fatal(err)
	}
	if readOut.Text == "" || readOut.ContentHash != match.ContentHash {
		t.Fatalf("unexpected read output: %#v", readOut)
	}

	quote := "European recovery to American economic power"
	_, quoteOut, err := client.validateQuote(ctx, nil, ValidateQuoteInput{
		BookID: "book-1", Quote: quote, ChapterID: "chapter-1",
		ExpectedSourceSHA256: "source-abc", ExpectedStructureDigest: bookOut.StructureDigest,
	})
	if err != nil {
		t.Fatal(err)
	}
	if !quoteOut.ExactMatch || !quoteOut.VersionMatch || len(quoteOut.Occurrences) != 1 {
		t.Fatalf("unexpected quote output: %#v", quoteOut)
	}
}

func TestMCPStreamableHTTPExposesOnlyResearchTools(t *testing.T) {
	upstream := fakeShelf(t)
	defer upstream.Close()
	mcpHTTP := httptest.NewServer(Handler(NewClient(upstream.URL, upstream.Client()), "test"))
	defer mcpHTTP.Close()

	client := mcp.NewClient(&mcp.Implementation{Name: "test-client", Version: "test"}, nil)
	session, err := client.Connect(context.Background(), &mcp.StreamableClientTransport{Endpoint: mcpHTTP.URL + "/mcp"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer session.Close()
	listed, err := session.ListTools(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]bool{
		"shelf_get_book": true, "shelf_list_structure": true, "shelf_search_passages": true,
		"shelf_read_passage": true, "shelf_validate_quote": true,
	}
	if len(listed.Tools) != len(want) {
		t.Fatalf("tool count = %d, want %d", len(listed.Tools), len(want))
	}
	for _, tool := range listed.Tools {
		if !want[tool.Name] {
			t.Fatalf("unexpected tool %q", tool.Name)
		}
	}
	result, err := session.CallTool(context.Background(), &mcp.CallToolParams{
		Name: "shelf_get_book", Arguments: map[string]any{"book_id": "book-1"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.IsError || result.StructuredContent == nil {
		t.Fatalf("unexpected MCP result: %#v", result)
	}
}
