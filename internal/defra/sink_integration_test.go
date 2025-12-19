package defra

import (
	"context"
	"log/slog"
	"os"
	"sync"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/testutil"
)

// setupIntegrationTest creates a DefraDB container and client for integration testing.
// Returns the client, sink, and a cleanup function.
func setupIntegrationTest(t *testing.T) (*Client, *Sink, func()) {
	t.Helper()

	// Register Docker cleanup
	_ = testutil.DockerClient(t)

	ctx := context.Background()
	dataPath := t.TempDir()
	containerName := testutil.UniqueContainerName(t, "sink")
	port, err := testutil.FindFreePort()
	if err != nil {
		t.Fatalf("failed to find free port: %v", err)
	}

	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo}))

	mgr, err := NewDockerManager(DockerConfig{
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
	client := NewClient(mgr.URL())

	// Wait for DefraDB to be healthy
	if err := client.HealthCheck(ctx); err != nil {
		mgr.Stop(ctx)
		mgr.Close()
		t.Fatalf("HealthCheck() error = %v", err)
	}

	// Add a simple test schema
	testSchema := `
		type TestDoc {
			name: String
			value: Int
			active: Boolean
		}
	`
	if err := client.AddSchema(ctx, testSchema); err != nil {
		// Ignore "already exists" errors
		t.Logf("AddSchema result: %v", err)
	}

	// Create sink
	sink := NewSink(SinkConfig{
		Client:        client,
		BatchSize:     10,
		FlushInterval: 100 * time.Millisecond,
		Logger:        logger,
	})
	sink.Start(ctx)

	cleanup := func() {
		sink.Stop()
		mgr.Stop(context.Background())
		mgr.Close()
	}

	return client, sink, cleanup
}

func TestSinkIntegration_CreateAndRead(t *testing.T) {
	client, sink, cleanup := setupIntegrationTest(t)
	defer cleanup()

	ctx := context.Background()

	// Create a document via sink
	result, err := sink.SendSync(ctx, WriteOp{
		Collection: "TestDoc",
		Document: map[string]any{
			"name":   "test-doc-1",
			"value":  42,
			"active": true,
		},
		Op: OpCreate,
	})
	if err != nil {
		t.Fatalf("SendSync create failed: %v", err)
	}
	if result.DocID == "" {
		t.Fatal("expected non-empty DocID")
	}

	t.Logf("Created document with ID: %s", result.DocID)

	// Read it back via client
	query := `{
		TestDoc {
			_docID
			name
			value
			active
		}
	}`
	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		t.Fatalf("Execute query failed: %v", err)
	}

	docs, ok := resp.Data["TestDoc"].([]any)
	if !ok || len(docs) == 0 {
		t.Fatalf("expected at least one document, got: %v", resp.Data)
	}

	doc := docs[0].(map[string]any)
	if doc["name"] != "test-doc-1" {
		t.Errorf("expected name 'test-doc-1', got %v", doc["name"])
	}
	if doc["value"].(float64) != 42 {
		t.Errorf("expected value 42, got %v", doc["value"])
	}
	if doc["active"] != true {
		t.Errorf("expected active true, got %v", doc["active"])
	}
}

func TestSinkIntegration_Update(t *testing.T) {
	client, sink, cleanup := setupIntegrationTest(t)
	defer cleanup()

	ctx := context.Background()

	// Create a document
	createResult, err := sink.SendSync(ctx, WriteOp{
		Collection: "TestDoc",
		Document: map[string]any{
			"name":   "update-test",
			"value":  100,
			"active": true,
		},
		Op: OpCreate,
	})
	if err != nil {
		t.Fatalf("SendSync create failed: %v", err)
	}

	// Update the document
	updateResult, err := sink.SendSync(ctx, WriteOp{
		Collection: "TestDoc",
		DocID:      createResult.DocID,
		Document: map[string]any{
			"value":  200,
			"active": false,
		},
		Op: OpUpdate,
	})
	if err != nil {
		t.Fatalf("SendSync update failed: %v", err)
	}
	if updateResult.DocID != createResult.DocID {
		t.Errorf("expected same DocID, got %s", updateResult.DocID)
	}

	// Read it back
	query := `{
		TestDoc(filter: {_docID: {_eq: "` + createResult.DocID + `"}}) {
			_docID
			name
			value
			active
		}
	}`
	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		t.Fatalf("Execute query failed: %v", err)
	}

	docs, ok := resp.Data["TestDoc"].([]any)
	if !ok || len(docs) == 0 {
		t.Fatalf("expected document, got: %v", resp.Data)
	}

	doc := docs[0].(map[string]any)
	if doc["name"] != "update-test" {
		t.Errorf("expected name 'update-test', got %v", doc["name"])
	}
	if doc["value"].(float64) != 200 {
		t.Errorf("expected value 200, got %v", doc["value"])
	}
	if doc["active"] != false {
		t.Errorf("expected active false, got %v", doc["active"])
	}
}

func TestSinkIntegration_Delete(t *testing.T) {
	client, sink, cleanup := setupIntegrationTest(t)
	defer cleanup()

	ctx := context.Background()

	// Create a document
	createResult, err := sink.SendSync(ctx, WriteOp{
		Collection: "TestDoc",
		Document: map[string]any{
			"name":  "delete-test",
			"value": 999,
		},
		Op: OpCreate,
	})
	if err != nil {
		t.Fatalf("SendSync create failed: %v", err)
	}

	// Delete the document
	_, err = sink.SendSync(ctx, WriteOp{
		Collection: "TestDoc",
		DocID:      createResult.DocID,
		Op:         OpDelete,
	})
	if err != nil {
		t.Fatalf("SendSync delete failed: %v", err)
	}

	// Verify it's gone
	query := `{
		TestDoc(filter: {_docID: {_eq: "` + createResult.DocID + `"}}) {
			_docID
		}
	}`
	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		t.Fatalf("Execute query failed: %v", err)
	}

	docs, ok := resp.Data["TestDoc"].([]any)
	if ok && len(docs) > 0 {
		t.Errorf("expected document to be deleted, but found: %v", docs)
	}
}

func TestSinkIntegration_FireAndForget(t *testing.T) {
	client, sink, cleanup := setupIntegrationTest(t)
	defer cleanup()

	ctx := context.Background()

	// Send multiple fire-and-forget writes
	for i := 0; i < 5; i++ {
		sink.Send(WriteOp{
			Collection: "TestDoc",
			Document: map[string]any{
				"name":  "fire-and-forget",
				"value": i,
			},
			Op: OpCreate,
		})
	}

	// Wait for flush
	time.Sleep(300 * time.Millisecond)

	// Verify all documents were created
	query := `{
		TestDoc(filter: {name: {_eq: "fire-and-forget"}}) {
			_docID
			value
		}
	}`
	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		t.Fatalf("Execute query failed: %v", err)
	}

	docs, ok := resp.Data["TestDoc"].([]any)
	if !ok {
		t.Fatalf("expected documents, got: %v", resp.Data)
	}
	if len(docs) != 5 {
		t.Errorf("expected 5 documents, got %d", len(docs))
	}
}

func TestSinkIntegration_ConcurrentWrites(t *testing.T) {
	client, sink, cleanup := setupIntegrationTest(t)
	defer cleanup()

	ctx := context.Background()

	// Concurrent writes from multiple goroutines
	var wg sync.WaitGroup
	numGoroutines := 10
	writesPerGoroutine := 5

	for g := 0; g < numGoroutines; g++ {
		wg.Add(1)
		go func(goroutineID int) {
			defer wg.Done()
			for i := 0; i < writesPerGoroutine; i++ {
				_, err := sink.SendSync(ctx, WriteOp{
					Collection: "TestDoc",
					Document: map[string]any{
						"name":  "concurrent-test",
						"value": goroutineID*100 + i,
					},
					Op: OpCreate,
				})
				if err != nil {
					t.Errorf("goroutine %d write %d failed: %v", goroutineID, i, err)
				}
			}
		}(g)
	}

	wg.Wait()

	// Verify all documents were created
	query := `{
		TestDoc(filter: {name: {_eq: "concurrent-test"}}) {
			_docID
		}
	}`
	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		t.Fatalf("Execute query failed: %v", err)
	}

	docs, ok := resp.Data["TestDoc"].([]any)
	if !ok {
		t.Fatalf("expected documents, got: %v", resp.Data)
	}

	expectedCount := numGoroutines * writesPerGoroutine
	if len(docs) != expectedCount {
		t.Errorf("expected %d documents, got %d", expectedCount, len(docs))
	}
}

func TestSinkIntegration_BatchFlush(t *testing.T) {
	client, sink, cleanup := setupIntegrationTest(t)
	defer cleanup()

	ctx := context.Background()

	// Send enough documents to trigger batch flush (batch size is 10)
	for i := 0; i < 15; i++ {
		sink.Send(WriteOp{
			Collection: "TestDoc",
			Document: map[string]any{
				"name":  "batch-test",
				"value": i,
			},
			Op: OpCreate,
		})
	}

	// Wait for flushes
	time.Sleep(300 * time.Millisecond)

	// Verify all documents were created
	query := `{
		TestDoc(filter: {name: {_eq: "batch-test"}}) {
			_docID
		}
	}`
	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		t.Fatalf("Execute query failed: %v", err)
	}

	docs, ok := resp.Data["TestDoc"].([]any)
	if !ok {
		t.Fatalf("expected documents, got: %v", resp.Data)
	}
	if len(docs) != 15 {
		t.Errorf("expected 15 documents, got %d", len(docs))
	}
}

func TestSinkIntegration_GracefulShutdown(t *testing.T) {
	// Register Docker cleanup
	_ = testutil.DockerClient(t)

	ctx := context.Background()
	dataPath := t.TempDir()
	containerName := testutil.UniqueContainerName(t, "shutdown")
	port, err := testutil.FindFreePort()
	if err != nil {
		t.Fatalf("failed to find free port: %v", err)
	}

	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo}))

	mgr, err := NewDockerManager(DockerConfig{
		ContainerName: containerName,
		DataPath:      dataPath,
		HostPort:      port,
		Labels:        testutil.ContainerLabels(t),
	})
	if err != nil {
		t.Fatalf("NewDockerManager() error = %v", err)
	}
	defer mgr.Close()
	defer mgr.Stop(context.Background())

	if err := mgr.Start(ctx); err != nil {
		t.Fatalf("Start() error = %v", err)
	}

	client := NewClient(mgr.URL())
	if err := client.HealthCheck(ctx); err != nil {
		t.Fatalf("HealthCheck() error = %v", err)
	}

	testSchema := `type TestDoc { name: String value: Int }`
	_ = client.AddSchema(ctx, testSchema)

	// Create sink with long flush interval (so only shutdown triggers flush)
	sink := NewSink(SinkConfig{
		Client:        client,
		BatchSize:     100, // Large batch
		FlushInterval: 10 * time.Second, // Long interval
		Logger:        logger,
	})
	sink.Start(ctx)

	// Send documents without waiting for flush
	for i := 0; i < 5; i++ {
		sink.Send(WriteOp{
			Collection: "TestDoc",
			Document: map[string]any{
				"name":  "shutdown-test",
				"value": i,
			},
			Op: OpCreate,
		})
	}

	// Stop should flush remaining
	sink.Stop()

	// Verify all documents were flushed before shutdown
	query := `{
		TestDoc(filter: {name: {_eq: "shutdown-test"}}) {
			_docID
		}
	}`
	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		t.Fatalf("Execute query failed: %v", err)
	}

	docs, ok := resp.Data["TestDoc"].([]any)
	if !ok {
		t.Fatalf("expected documents, got: %v", resp.Data)
	}
	if len(docs) != 5 {
		t.Errorf("expected 5 documents after graceful shutdown, got %d", len(docs))
	}
}
