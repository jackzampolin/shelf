package common

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/testutil"
)

// setupStateIntegrationTest creates a DefraDB container with schemas for BookState testing.
// Returns the client, sink, DefraStateStore, and a cleanup function.
func setupStateIntegrationTest(t *testing.T) (*defra.Client, *defra.Sink, *DefraStateStore, func()) {
	t.Helper()

	// Register Docker cleanup
	_ = testutil.DockerClient(t)

	ctx := context.Background()
	dataPath := t.TempDir()
	containerName := testutil.UniqueContainerName(t, "state")
	port, err := testutil.FindFreePort()
	if err != nil {
		t.Fatalf("failed to find free port: %v", err)
	}

	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo}))

	mgr, err := defra.NewDockerManager(defra.DockerConfig{
		ContainerName: containerName,
		DataPath:      dataPath,
		HostPort:      port,
		Labels:        testutil.ContainerLabels(t),
	})
	if err != nil {
		t.Fatalf("NewDockerManager() error = %v", err)
	}

	// Start DefraDB
	if err := mgr.Start(ctx); err != nil {
		mgr.Close()
		t.Fatalf("Start() error = %v", err)
	}

	// Create client
	client := defra.NewClient(mgr.URL())

	// Wait for DefraDB to be healthy
	if err := client.HealthCheck(ctx); err != nil {
		mgr.Stop(ctx)
		mgr.Close()
		t.Fatalf("HealthCheck() error = %v", err)
	}

	// Add schemas for BookState testing
	schemas := []string{
		// Book schema (simplified for testing)
		`type Book {
			title: String
			status: String
			metadata_started: Boolean
			metadata_complete: Boolean
			metadata_failed: Boolean
			metadata_retries: Int
			pattern_analysis_started: Boolean
			pattern_analysis_complete: Boolean
			pattern_analysis_failed: Boolean
			pattern_analysis_retries: Int
			structure_started: Boolean
			structure_complete: Boolean
			structure_failed: Boolean
			structure_retries: Int
			structure_phase: String
			structure_chapters_total: Int
			structure_chapters_extracted: Int
			structure_chapters_polished: Int
			structure_polish_failed: Int
			page_pattern_analysis_json: String
			total_chapters: Int
			total_paragraphs: Int
			total_words: Int
		}`,
		// ToC schema
		`type ToC {
			book_id: String
			toc_found: Boolean
			start_page: Int
			end_page: Int
			finder_started: Boolean
			finder_complete: Boolean
			finder_failed: Boolean
			finder_retries: Int
			extract_started: Boolean
			extract_complete: Boolean
			extract_failed: Boolean
			extract_retries: Int
			link_started: Boolean
			link_complete: Boolean
			link_failed: Boolean
			link_retries: Int
			finalize_started: Boolean
			finalize_complete: Boolean
			finalize_failed: Boolean
			finalize_retries: Int
			finalize_phase: String
		}`,
		// TocEntry schema
		`type TocEntry {
			toc_id: String
			title: String
			level: Int
			sort_order: Int
			actual_page_id: String
		}`,
		// Chapter schema
		`type Chapter {
			book_id: String
			title: String
			sort_order: Int
		}`,
		// AgentState schema
		`type AgentState {
			agent_id: String
			agent_type: String
			book_id: String
			complete: Boolean
		}`,
	}

	for _, schema := range schemas {
		if err := client.AddSchema(ctx, schema); err != nil {
			t.Logf("AddSchema result: %v", err)
		}
	}

	// Create sink
	sink := defra.NewSink(defra.SinkConfig{
		Client:        client,
		BatchSize:     10,
		FlushInterval: 100 * time.Millisecond,
		Logger:        logger,
	})
	sink.Start(ctx)

	// Create DefraStateStore
	store := &DefraStateStore{
		Client: client,
		Sink:   sink,
	}

	cleanup := func() {
		sink.Stop()
		mgr.Stop(context.Background())
		mgr.Close()
	}

	return client, sink, store, cleanup
}

func TestStateIntegration_PersistAndReload(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	client, _, store, cleanup := setupStateIntegrationTest(t)
	defer cleanup()

	ctx := context.Background()

	// Create a Book document
	bookResult, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		Document: map[string]any{
			"title":  "Test Book",
			"status": "processing",
		},
		Op: defra.OpCreate,
	})
	if err != nil {
		t.Fatalf("failed to create book: %v", err)
	}
	bookDocID := bookResult.DocID
	t.Logf("Created book with DocID: %s", bookDocID)

	// Create a ToC document
	tocResult, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "ToC",
		Document: map[string]any{
			"book_id": bookDocID,
		},
		Op: defra.OpCreate,
	})
	if err != nil {
		t.Fatalf("failed to create ToC: %v", err)
	}
	tocDocID := tocResult.DocID
	t.Logf("Created ToC with DocID: %s", tocDocID)

	// Create BookState and wire up the store
	book := NewBookState("test-book-id")
	book.BookDocID = bookDocID
	book.SetTocDocID(tocDocID)
	book.Store = store

	// Start and complete metadata operation
	if err := book.OpStart(OpMetadata); err != nil {
		t.Fatalf("OpStart(metadata) failed: %v", err)
	}
	book.OpComplete(OpMetadata)

	// Persist metadata state
	if err := PersistOpStateSync(ctx, book, OpMetadata); err != nil {
		t.Fatalf("PersistOpStateSync(metadata) failed: %v", err)
	}

	// Start ToC finder and fail it
	if err := book.OpStart(OpTocFinder); err != nil {
		t.Fatalf("OpStart(toc_finder) failed: %v", err)
	}
	book.OpFail(OpTocFinder, 3)

	// Persist ToC finder state
	if err := PersistOpStateSync(ctx, book, OpTocFinder); err != nil {
		t.Fatalf("PersistOpStateSync(toc_finder) failed: %v", err)
	}

	// Read back from DB and verify
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			_docID
			metadata_started
			metadata_complete
			metadata_failed
			metadata_retries
		}
	}`, bookDocID)

	bookResp, err := client.Execute(ctx, bookQuery, nil)
	if err != nil {
		t.Fatalf("failed to query book: %v", err)
	}

	books, ok := bookResp.Data["Book"].([]any)
	if !ok || len(books) == 0 {
		t.Fatalf("expected book document, got: %v", bookResp.Data)
	}

	bookDoc := books[0].(map[string]any)
	// When Complete(), IsStarted() returns false (status is OpComplete, not OpInProgress)
	if bookDoc["metadata_started"] != false {
		t.Errorf("expected metadata_started=false (completed ops are not 'started'), got %v", bookDoc["metadata_started"])
	}
	if bookDoc["metadata_complete"] != true {
		t.Errorf("expected metadata_complete=true, got %v", bookDoc["metadata_complete"])
	}
	if bookDoc["metadata_failed"] != false {
		t.Errorf("expected metadata_failed=false, got %v", bookDoc["metadata_failed"])
	}

	// Verify ToC finder state
	tocQuery := fmt.Sprintf(`{
		ToC(filter: {_docID: {_eq: "%s"}}) {
			_docID
			finder_started
			finder_complete
			finder_failed
			finder_retries
		}
	}`, tocDocID)

	tocResp, err := client.Execute(ctx, tocQuery, nil)
	if err != nil {
		t.Fatalf("failed to query ToC: %v", err)
	}

	tocs, ok := tocResp.Data["ToC"].([]any)
	if !ok || len(tocs) == 0 {
		t.Fatalf("expected ToC document, got: %v", tocResp.Data)
	}

	tocDoc := tocs[0].(map[string]any)
	if tocDoc["finder_started"] != false {
		t.Errorf("expected finder_started=false (after fail), got %v", tocDoc["finder_started"])
	}
	if tocDoc["finder_complete"] != false {
		t.Errorf("expected finder_complete=false, got %v", tocDoc["finder_complete"])
	}
	if tocDoc["finder_failed"] != false {
		t.Errorf("expected finder_failed=false (retries not exhausted), got %v", tocDoc["finder_failed"])
	}
	if tocDoc["finder_retries"].(float64) != 1 {
		t.Errorf("expected finder_retries=1, got %v", tocDoc["finder_retries"])
	}
}

func TestStateIntegration_ResetCascade(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	_, _, store, cleanup := setupStateIntegrationTest(t)
	defer cleanup()

	ctx := context.Background()

	// Create a Book document
	bookResult, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		Document: map[string]any{
			"title":  "Cascade Test Book",
			"status": "processing",
		},
		Op: defra.OpCreate,
	})
	if err != nil {
		t.Fatalf("failed to create book: %v", err)
	}
	bookDocID := bookResult.DocID

	// Create a ToC document
	tocResult, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "ToC",
		Document: map[string]any{
			"book_id":          bookDocID,
			"finder_started":   false,
			"finder_complete":  true,
			"extract_started":  false,
			"extract_complete": true,
			"link_started":     false,
			"link_complete":    true,
		},
		Op: defra.OpCreate,
	})
	if err != nil {
		t.Fatalf("failed to create ToC: %v", err)
	}
	tocDocID := tocResult.DocID

	// Create TocEntry documents
	for i := 0; i < 3; i++ {
		_, err := store.SendSync(ctx, defra.WriteOp{
			Collection: "TocEntry",
			Document: map[string]any{
				"toc_id":     tocDocID,
				"title":      fmt.Sprintf("Chapter %d", i+1),
				"level":      1,
				"sort_order": i,
			},
			Op: defra.OpCreate,
		})
		if err != nil {
			t.Fatalf("failed to create TocEntry %d: %v", i, err)
		}
	}

	// Create AgentState documents
	for i := 0; i < 2; i++ {
		_, err := store.SendSync(ctx, defra.WriteOp{
			Collection: "AgentState",
			Document: map[string]any{
				"agent_id":   fmt.Sprintf("agent-%d", i),
				"agent_type": "toc_extract",
				"book_id":    bookDocID,
				"complete":   true,
			},
			Op: defra.OpCreate,
		})
		if err != nil {
			t.Fatalf("failed to create AgentState %d: %v", i, err)
		}
	}

	// Verify TocEntries exist
	entriesQuery := fmt.Sprintf(`{
		TocEntry(filter: {toc_id: {_eq: "%s"}}) {
			_docID
		}
	}`, tocDocID)
	entriesResp, err := store.Execute(ctx, entriesQuery, nil)
	if err != nil {
		t.Fatalf("failed to query TocEntries: %v", err)
	}
	entries := entriesResp.Data["TocEntry"].([]any)
	if len(entries) != 3 {
		t.Fatalf("expected 3 TocEntries, got %d", len(entries))
	}

	// Create BookState with completed operations
	book := NewBookState(bookDocID)
	book.BookDocID = bookDocID
	book.SetTocDocID(tocDocID)
	book.Store = store

	// Set up completed states
	book.SetOpState(OpTocFinder, false, true, false, 0)
	book.SetOpState(OpTocExtract, false, true, false, 0)
	book.SetOpState(OpTocLink, false, true, false, 0)

	// Reset toc_extract - should cascade to toc_link and delete TocEntries
	if err := ResetFrom(ctx, book, tocDocID, ResetTocExtract); err != nil {
		t.Fatalf("ResetFrom(toc_extract) failed: %v", err)
	}

	// Verify TocEntries were deleted
	entriesResp, err = store.Execute(ctx, entriesQuery, nil)
	if err != nil {
		t.Fatalf("failed to query TocEntries after reset: %v", err)
	}
	entries, ok := entriesResp.Data["TocEntry"].([]any)
	if ok && len(entries) != 0 {
		t.Errorf("expected TocEntries to be deleted, got %d", len(entries))
	}

	// Verify toc_extract was reset
	if book.OpIsComplete(OpTocExtract) {
		t.Error("expected toc_extract to be reset (not complete)")
	}

	// Verify toc_link was cascade-reset
	if book.OpIsComplete(OpTocLink) {
		t.Error("expected toc_link to be cascade-reset (not complete)")
	}

	// Verify toc_finder was NOT reset (upstream)
	if !book.OpIsComplete(OpTocFinder) {
		t.Error("expected toc_finder to remain complete (not part of cascade)")
	}

	// Verify AgentStates for toc_extract were deleted
	agentsQuery := fmt.Sprintf(`{
		AgentState(filter: {book_id: {_eq: "%s"}, agent_type: {_eq: "toc_extract"}}) {
			_docID
		}
	}`, bookDocID)
	agentsResp, err := store.Execute(ctx, agentsQuery, nil)
	if err != nil {
		t.Fatalf("failed to query AgentStates: %v", err)
	}
	agents, ok := agentsResp.Data["AgentState"].([]any)
	if ok && len(agents) != 0 {
		t.Errorf("expected toc_extract AgentStates to be deleted, got %d", len(agents))
	}
}

func TestStateIntegration_StructureReset(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	_, _, store, cleanup := setupStateIntegrationTest(t)
	defer cleanup()

	ctx := context.Background()

	// Create a Book document
	bookResult, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		Document: map[string]any{
			"title":                       "Structure Test Book",
			"status":                      "processing",
			"structure_started":           false,
			"structure_complete":          true,
			"structure_phase":             "done",
			"structure_chapters_total":    5,
			"structure_chapters_polished": 5,
		},
		Op: defra.OpCreate,
	})
	if err != nil {
		t.Fatalf("failed to create book: %v", err)
	}
	bookDocID := bookResult.DocID

	// Create Chapter documents
	for i := 0; i < 5; i++ {
		_, err := store.SendSync(ctx, defra.WriteOp{
			Collection: "Chapter",
			Document: map[string]any{
				"book_id":    bookDocID,
				"title":      fmt.Sprintf("Chapter %d", i+1),
				"sort_order": i,
			},
			Op: defra.OpCreate,
		})
		if err != nil {
			t.Fatalf("failed to create Chapter %d: %v", i, err)
		}
	}

	// Verify Chapters exist
	chaptersQuery := fmt.Sprintf(`{
		Chapter(filter: {book_id: {_eq: "%s"}}) {
			_docID
		}
	}`, bookDocID)
	chaptersResp, err := store.Execute(ctx, chaptersQuery, nil)
	if err != nil {
		t.Fatalf("failed to query Chapters: %v", err)
	}
	chapters := chaptersResp.Data["Chapter"].([]any)
	if len(chapters) != 5 {
		t.Fatalf("expected 5 Chapters, got %d", len(chapters))
	}

	// Create BookState with completed structure
	book := NewBookState(bookDocID)
	book.BookDocID = bookDocID
	book.Store = store
	book.SetOpState(OpStructure, false, true, false, 0)

	// Reset structure - should delete Chapters
	if err := ResetFrom(ctx, book, "", ResetStructure); err != nil {
		t.Fatalf("ResetFrom(structure) failed: %v", err)
	}

	// Verify Chapters were deleted
	chaptersResp, err = store.Execute(ctx, chaptersQuery, nil)
	if err != nil {
		t.Fatalf("failed to query Chapters after reset: %v", err)
	}
	chapters, ok := chaptersResp.Data["Chapter"].([]any)
	if ok && len(chapters) != 0 {
		t.Errorf("expected Chapters to be deleted, got %d", len(chapters))
	}

	// Verify structure was reset
	if book.OpIsComplete(OpStructure) {
		t.Error("expected structure to be reset (not complete)")
	}
}

func TestStateIntegration_ConcurrentPersist(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	client, _, store, cleanup := setupStateIntegrationTest(t)
	defer cleanup()

	ctx := context.Background()

	// Create a Book document
	bookResult, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		Document: map[string]any{
			"title":  "Concurrent Test Book",
			"status": "processing",
		},
		Op: defra.OpCreate,
	})
	if err != nil {
		t.Fatalf("failed to create book: %v", err)
	}
	bookDocID := bookResult.DocID

	// Create BookState
	book := NewBookState("test-book")
	book.BookDocID = bookDocID
	book.Store = store

	// Run multiple persist operations concurrently
	done := make(chan error, 10)
	for i := 0; i < 10; i++ {
		go func(iteration int) {
			// Alternate between starting and completing
			if iteration%2 == 0 {
				_ = book.OpStart(OpMetadata)
			} else {
				book.OpComplete(OpMetadata)
			}
			err := PersistOpStateSync(ctx, book, OpMetadata)
			done <- err
		}(i)
	}

	// Wait for all goroutines
	for i := 0; i < 10; i++ {
		if err := <-done; err != nil {
			t.Errorf("concurrent persist %d failed: %v", i, err)
		}
	}

	// Verify the final state is consistent
	query := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			metadata_started
			metadata_complete
		}
	}`, bookDocID)

	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		t.Fatalf("failed to query book: %v", err)
	}

	books, ok := resp.Data["Book"].([]any)
	if !ok || len(books) == 0 {
		t.Fatalf("expected book document")
	}

	// Just verify we got valid boolean values (the actual state depends on race)
	bookDoc := books[0].(map[string]any)
	_, startedOk := bookDoc["metadata_started"].(bool)
	_, completeOk := bookDoc["metadata_complete"].(bool)
	if !startedOk || !completeOk {
		t.Errorf("expected boolean values for metadata state, got started=%T complete=%T",
			bookDoc["metadata_started"], bookDoc["metadata_complete"])
	}
}
