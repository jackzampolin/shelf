package job

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

func newStructureResponseFormatJob() *Job {
	book := common.NewBookState("book-1")
	book.TotalPages = 10
	book.TocProvider = "qwen-local"
	book.SetStructureChapters([]*common.ChapterState{
		{
			EntryID:        "ch_001",
			Title:          "Chapter One",
			Level:          1,
			LevelName:      "chapter",
			StartPage:      1,
			EndPage:        3,
			MechanicalText: "Chapter text.",
			WordCount:      2,
		},
	})

	return NewFromLoadResult(&common.LoadBookResult{Book: book})
}

func TestCreateStructureClassifyWorkUnitUsesInnerJSONSchema(t *testing.T) {
	j := newStructureResponseFormatJob()

	unit, err := j.createStructureClassifyWorkUnit(context.Background())
	if err != nil {
		t.Fatalf("createStructureClassifyWorkUnit error: %v", err)
	}

	assertResponseFormatSchemaName(t, unit.ChatRequest.ResponseFormat.JSONSchema, "entry_classifications")
}

func TestCreateChapterPolishWorkUnitUsesInnerJSONSchema(t *testing.T) {
	j := newStructureResponseFormatJob()
	chapter := j.Book.GetStructureChapters()[0]

	unit := j.createChapterPolishWorkUnit(context.Background(), chapter)
	if unit == nil {
		t.Fatal("createChapterPolishWorkUnit returned nil")
	}

	if unit.ChatRequest.MaxTokens != common.MaxPolishOutputTokens {
		t.Fatalf("polish MaxTokens = %d, want %d", unit.ChatRequest.MaxTokens, common.MaxPolishOutputTokens)
	}
	assertResponseFormatSchemaName(t, unit.ChatRequest.ResponseFormat.JSONSchema, "text_edits")
}

func TestFailedStructurePolishErrorNamesChapter(t *testing.T) {
	err := failedWorkUnitError(WorkUnitInfo{
		UnitType:  WorkUnitTypeStructurePolish,
		ChapterID: "ch_007",
	}, errors.New("model output reached token limit"))
	for _, want := range []string{"structure_polish", "chapter=ch_007", "model output reached token limit"} {
		if !strings.Contains(err.Error(), want) {
			t.Fatalf("error %q missing %q", err, want)
		}
	}
}

func TestFailedBookOperationErrorDoesNotClaimPageZero(t *testing.T) {
	err := failedWorkUnitError(WorkUnitInfo{
		UnitType: WorkUnitTypeTocExtract,
	}, errors.New("model output reached token limit"))
	for _, want := range []string{"toc_extract", "retries=0", "model output reached token limit"} {
		if !strings.Contains(err.Error(), want) {
			t.Fatalf("error %q missing %q", err, want)
		}
	}
	if strings.Contains(err.Error(), "page=") {
		t.Fatalf("book-operation error claimed a page: %q", err)
	}
}

func TestIsDefraDocIDExistsError(t *testing.T) {
	err := errors.New("upsert error: a document with the given ID already exists. DocID: bae-123")
	if !isDefraDocIDExistsError(err) {
		t.Fatal("expected DocID exists error to be detected")
	}
	if isDefraDocIDExistsError(errors.New("upsert error: transaction conflict")) {
		t.Fatal("transaction conflict should not be treated as DocID exists")
	}
}

func TestDefraStructureWriteWithRetryRetriesTransactionConflict(t *testing.T) {
	attempts := 0
	result, err := defraStructureWriteWithRetry(context.Background(), func() (defra.WriteResult, error) {
		attempts++
		if attempts < 3 {
			return defra.WriteResult{}, errors.New("update error: transaction conflict. Please retry")
		}
		return defra.WriteResult{DocID: "chapter-doc", CID: "cid-1"}, nil
	})
	if err != nil {
		t.Fatalf("defraStructureWriteWithRetry error: %v", err)
	}
	if attempts != 3 {
		t.Fatalf("attempts = %d, want 3", attempts)
	}
	if result.DocID != "chapter-doc" || result.CID != "cid-1" {
		t.Fatalf("result = %+v, want chapter-doc/cid-1", result)
	}
}

func TestDefraStructureWriteWithRetryRetriesTransientServerError(t *testing.T) {
	attempts := 0
	_, err := defraStructureWriteWithRetry(context.Background(), func() (defra.WriteResult, error) {
		attempts++
		if attempts < 3 {
			return defra.WriteResult{}, errors.New("defra server error (status 500)")
		}
		return defra.WriteResult{DocID: "chapter-doc"}, nil
	})
	if err != nil {
		t.Fatalf("defraStructureWriteWithRetry error: %v", err)
	}
	if attempts != 3 {
		t.Fatalf("attempts = %d, want 3", attempts)
	}
}

func TestPersistChapterSkeletonDocUpdatesExistingIdentityAfterDocIDCollision(t *testing.T) {
	book := common.NewBookState("book-1")
	j := NewFromLoadResult(&common.LoadBookResult{Book: book})
	chapter := &common.ChapterState{
		EntryID:    "ch_001",
		UniqueKey:  "book-1:toc-1",
		TocEntryID: "toc-1",
		SortOrder:  100,
	}
	doc := map[string]any{
		"_bookID":      "book-1",
		"_toc_entryID": "toc-1",
		"unique_key":   "book-1:toc-1",
		"entry_id":     "ch_001",
		"title":        "Chapter One",
		"sort_order":   100,
	}

	var requests []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Query string `json:"query"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatalf("failed to decode request body: %v", err)
		}
		requests = append(requests, body.Query)

		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.Contains(body.Query, "upsert_Chapter"):
			w.Write([]byte(`{"errors":[{"message":"a document with the given ID already exists. DocID: bae-hidden"}]}`))
		case strings.Contains(body.Query, "Chapter(filter"):
			w.Write([]byte(`{"data":{"Chapter":[{"_docID":"chapter-doc","unique_key":"book-1:toc-1:recreated:old","entry_id":"ch_001","sort_order":100,"_toc_entryID":"toc-1"}]}}`))
		case strings.Contains(body.Query, "update_Chapter"):
			if strings.Contains(body.Query, ":recreated:") {
				t.Fatalf("update mutation kept recreated key: %s", body.Query)
			}
			if !strings.Contains(body.Query, `docID: "chapter-doc"`) {
				t.Fatalf("update mutation did not target existing doc: %s", body.Query)
			}
			if !strings.Contains(body.Query, `unique_key: "book-1:toc-1"`) {
				t.Fatalf("update mutation did not persist stable key: %s", body.Query)
			}
			w.Write([]byte(`{"data":{"update_Chapter":[{"_docID":"chapter-doc","_version":[{"cid":"cid-1"}]}]}}`))
		default:
			t.Fatalf("unexpected query: %s", body.Query)
		}
	}))
	defer server.Close()

	client := defra.NewClient(server.URL)
	result, err := j.persistChapterSkeletonDoc(context.Background(), client, chapter, doc)
	if err != nil {
		t.Fatalf("persistChapterSkeletonDoc error: %v", err)
	}
	if result.DocID != "chapter-doc" || result.CID != "cid-1" {
		t.Fatalf("result = %+v, want chapter-doc/cid-1", result)
	}
	if len(requests) != 3 {
		t.Fatalf("requests = %d, want 3: %#v", len(requests), requests)
	}
	for _, req := range requests {
		if strings.Contains(req, "add_Chapter") {
			t.Fatalf("collision path created a new chapter: %s", req)
		}
	}
}

func TestAttachExistingChapterDocIDsUsesStableTocIdentity(t *testing.T) {
	book := common.NewBookState("book-1")
	chapter := &common.ChapterState{
		EntryID:    "ch_001",
		UniqueKey:  "book-1:toc-1",
		TocEntryID: "toc-1",
		SortOrder:  100,
	}
	book.SetStructureChapters([]*common.ChapterState{chapter})
	j := NewFromLoadResult(&common.LoadBookResult{Book: book})

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":{"Chapter":[{"_docID":"chapter-doc","unique_key":"old-key","entry_id":"ch_001","sort_order":100,"_toc_entryID":"toc-1"}]}}`))
	}))
	defer server.Close()

	if err := j.attachExistingChapterDocIDs(context.Background(), defra.NewClient(server.URL), []*common.ChapterState{chapter}); err != nil {
		t.Fatal(err)
	}
	if chapter.DocID != "chapter-doc" {
		t.Fatalf("chapter DocID = %q, want existing chapter-doc", chapter.DocID)
	}
}

func TestValidatePersistedStructureChaptersRejectsMissingPersistedFields(t *testing.T) {
	book := common.NewBookState("book-1")
	book.SetStructureChapters([]*common.ChapterState{
		{
			EntryID:    "ch_016",
			DocID:      "chapter-doc",
			TocEntryID: "toc-1",
			SortOrder:  1600,
			PolishDone: true,
		},
	})
	j := NewFromLoadResult(&common.LoadBookResult{Book: book})

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":{"Chapter":[{"_docID":"chapter-doc","entry_id":"ch_016","sort_order":1600,"_toc_entryID":"toc-1","extract_complete":null,"polish_complete":true,"matter_type":"body","content_type":null,"audio_include":null}]}}`))
	}))
	defer server.Close()

	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient: defra.NewClient(server.URL),
	})
	err := j.validatePersistedStructureChapters(ctx)
	if err == nil {
		t.Fatal("expected validation error")
	}
	for _, want := range []string{
		"ch_016 missing extract_complete",
		"ch_016 missing content_type",
		"ch_016 missing audio_include",
	} {
		if !strings.Contains(err.Error(), want) {
			t.Fatalf("validation error missing %q: %v", want, err)
		}
	}
}

func TestValidatePersistedStructureChaptersAcceptsFalseAudioInclude(t *testing.T) {
	book := common.NewBookState("book-1")
	book.SetStructureChapters([]*common.ChapterState{
		{
			EntryID:    "ch_029",
			DocID:      "chapter-doc",
			TocEntryID: "toc-1",
			SortOrder:  2900,
			PolishDone: true,
		},
	})
	j := NewFromLoadResult(&common.LoadBookResult{Book: book})

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":{"Chapter":[{"_docID":"chapter-doc","entry_id":"ch_029","sort_order":2900,"_toc_entryID":"toc-1","extract_complete":true,"polish_complete":true,"matter_type":"back_matter","content_type":"appendix","audio_include":false}]}}`))
	}))
	defer server.Close()

	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient: defra.NewClient(server.URL),
	})
	if err := j.validatePersistedStructureChapters(ctx); err != nil {
		t.Fatalf("validatePersistedStructureChapters error: %v", err)
	}
}

func TestDeleteStaleStructureChaptersDeletesRowsOutsideCurrentSkeleton(t *testing.T) {
	book := common.NewBookState("book-1")
	j := NewFromLoadResult(&common.LoadBookResult{Book: book})
	current := []*common.ChapterState{{DocID: "keep-doc", EntryID: "ch_001"}}

	deleted := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Query string `json:"query"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatalf("failed to decode request body: %v", err)
		}
		w.Header().Set("Content-Type", "application/json")

		switch {
		case strings.Contains(body.Query, "Chapter(filter"):
			w.Write([]byte(`{"data":{"Chapter":[{"_docID":"keep-doc","entry_id":"ch_001","sort_order":100,"_toc_entryID":"toc-1"},{"_docID":"stale-doc","entry_id":"old","sort_order":999,"_toc_entryID":"old-toc"}]}}`))
		case strings.Contains(body.Query, "delete_Chapter"):
			if !strings.Contains(body.Query, `docID: "stale-doc"`) {
				t.Fatalf("deleted wrong chapter: %s", body.Query)
			}
			deleted++
			w.Write([]byte(`{"data":{"delete_Chapter":[{"_docID":"stale-doc"}]}}`))
		default:
			t.Fatalf("unexpected query: %s", body.Query)
		}
	}))
	defer server.Close()

	client := defra.NewClient(server.URL)
	if err := j.deleteStaleStructureChapters(context.Background(), client, current); err != nil {
		t.Fatalf("deleteStaleStructureChapters error: %v", err)
	}
	if deleted != 1 {
		t.Fatalf("deleted = %d, want 1", deleted)
	}
}

func TestPolishJSONSchemaCapsEditArray(t *testing.T) {
	schema := common.PolishJSONSchema()
	payload := schema["schema"].(map[string]any)
	props := payload["properties"].(map[string]any)
	edits := props["edits"].(map[string]any)
	if edits["maxItems"] != 50 {
		t.Fatalf("edits.maxItems = %v, want 50", edits["maxItems"])
	}
}

func TestComputeStructureStatsUsesChapterWordCountsAndFallbackText(t *testing.T) {
	chapters := []*common.ChapterState{
		{EntryID: "ch_001", WordCount: 10, PolishedText: "ignored because explicit count wins"},
		{EntryID: "ch_002", PolishedText: "four words right here"},
		{EntryID: "ch_003", MechanicalText: "fallback has three"},
		nil,
	}

	totalChapters, totalWords := computeStructureStats(chapters)
	if totalChapters != 3 {
		t.Fatalf("totalChapters = %d, want 3", totalChapters)
	}
	if totalWords != 17 {
		t.Fatalf("totalWords = %d, want 17", totalWords)
	}
}

func assertResponseFormatSchemaName(t *testing.T, raw json.RawMessage, want string) {
	t.Helper()
	if string(raw) == "null" || len(raw) == 0 {
		t.Fatalf("response format schema is %q, want object with name %q", string(raw), want)
	}

	var schema map[string]any
	if err := json.Unmarshal(raw, &schema); err != nil {
		t.Fatalf("failed to unmarshal response format schema: %v", err)
	}
	if got, _ := schema["name"].(string); got != want {
		t.Fatalf("schema name = %q, want %q; schema=%s", got, want, string(raw))
	}
	if _, ok := schema["schema"].(map[string]any); !ok {
		t.Fatalf("schema payload missing nested schema object: %s", string(raw))
	}
}
