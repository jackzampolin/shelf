package defra

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// mockDefraServer creates a test server that simulates DefraDB GraphQL responses.
func mockDefraServer(t *testing.T, handler func(w http.ResponseWriter, r *http.Request)) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(handler))
}

func TestSink_SendSync_Create(t *testing.T) {
	var requestCount atomic.Int32

	server := mockDefraServer(t, func(w http.ResponseWriter, r *http.Request) {
		requestCount.Add(1)

		resp := GQLResponse{
			Data: map[string]any{
				"create_TestDoc": []any{
					map[string]any{"_docID": "doc123"},
				},
			},
		}
		json.NewEncoder(w).Encode(resp)
	})
	defer server.Close()

	client := NewClient(server.URL)
	sink := NewSink(SinkConfig{
		Client:        client,
		BatchSize:     10,
		FlushInterval: 100 * time.Millisecond,
	})

	ctx := context.Background()
	sink.Start(ctx)
	defer sink.Stop()

	result, err := sink.SendSync(ctx, WriteOp{
		Collection: "TestDoc",
		Document:   map[string]any{"name": "test"},
		Op:         OpCreate,
	})

	if err != nil {
		t.Fatalf("SendSync failed: %v", err)
	}
	if result.DocID != "doc123" {
		t.Errorf("expected docID 'doc123', got %q", result.DocID)
	}
}

func TestSink_Send_FireAndForget(t *testing.T) {
	var requestCount atomic.Int32

	server := mockDefraServer(t, func(w http.ResponseWriter, r *http.Request) {
		requestCount.Add(1)

		resp := GQLResponse{
			Data: map[string]any{
				"create_Metric": []any{
					map[string]any{"_docID": "metric123"},
				},
			},
		}
		json.NewEncoder(w).Encode(resp)
	})
	defer server.Close()

	client := NewClient(server.URL)
	sink := NewSink(SinkConfig{
		Client:        client,
		BatchSize:     10,
		FlushInterval: 50 * time.Millisecond,
	})

	ctx := context.Background()
	sink.Start(ctx)

	// Send fire-and-forget
	sink.Send(WriteOp{
		Collection: "Metric",
		Document:   map[string]any{"value": 42},
		Op:         OpCreate,
	})

	// Give time for flush
	time.Sleep(100 * time.Millisecond)
	sink.Stop()

	if requestCount.Load() != 1 {
		t.Errorf("expected 1 request, got %d", requestCount.Load())
	}
}

func TestSink_BatchBySize(t *testing.T) {
	var requestCount atomic.Int32
	var mu sync.Mutex
	var collections []string

	server := mockDefraServer(t, func(w http.ResponseWriter, r *http.Request) {
		requestCount.Add(1)

		var req GQLRequest
		json.NewDecoder(r.Body).Decode(&req)

		mu.Lock()
		collections = append(collections, req.Query)
		mu.Unlock()

		resp := GQLResponse{
			Data: map[string]any{
				"create_TestDoc": []any{
					map[string]any{"_docID": "doc123"},
				},
			},
		}
		json.NewEncoder(w).Encode(resp)
	})
	defer server.Close()

	client := NewClient(server.URL)
	sink := NewSink(SinkConfig{
		Client:        client,
		BatchSize:     3, // Small batch size for testing
		FlushInterval: 10 * time.Second, // Long interval so batch size triggers first
	})

	ctx := context.Background()
	sink.Start(ctx)

	// Send 3 ops to trigger batch
	for i := 0; i < 3; i++ {
		sink.Send(WriteOp{
			Collection: "TestDoc",
			Document:   map[string]any{"index": i},
			Op:         OpCreate,
		})
	}

	// Wait for processing
	time.Sleep(100 * time.Millisecond)
	sink.Stop()

	// Should have made 3 requests (one per create, since we don't have batch API yet)
	if requestCount.Load() != 3 {
		t.Errorf("expected 3 requests, got %d", requestCount.Load())
	}
}

func TestSink_BatchByTime(t *testing.T) {
	var requestCount atomic.Int32

	server := mockDefraServer(t, func(w http.ResponseWriter, r *http.Request) {
		requestCount.Add(1)

		resp := GQLResponse{
			Data: map[string]any{
				"create_TestDoc": []any{
					map[string]any{"_docID": "doc123"},
				},
			},
		}
		json.NewEncoder(w).Encode(resp)
	})
	defer server.Close()

	client := NewClient(server.URL)
	sink := NewSink(SinkConfig{
		Client:        client,
		BatchSize:     100, // Large batch so time triggers first
		FlushInterval: 50 * time.Millisecond,
	})

	ctx := context.Background()
	sink.Start(ctx)

	// Send 1 op (won't trigger batch by size)
	sink.Send(WriteOp{
		Collection: "TestDoc",
		Document:   map[string]any{"name": "test"},
		Op:         OpCreate,
	})

	// Wait for time-based flush
	time.Sleep(100 * time.Millisecond)
	sink.Stop()

	if requestCount.Load() != 1 {
		t.Errorf("expected 1 request from time flush, got %d", requestCount.Load())
	}
}

func TestSink_GracefulShutdown(t *testing.T) {
	var requestCount atomic.Int32

	server := mockDefraServer(t, func(w http.ResponseWriter, r *http.Request) {
		requestCount.Add(1)

		resp := GQLResponse{
			Data: map[string]any{
				"create_TestDoc": []any{
					map[string]any{"_docID": "doc123"},
				},
			},
		}
		json.NewEncoder(w).Encode(resp)
	})
	defer server.Close()

	client := NewClient(server.URL)
	sink := NewSink(SinkConfig{
		Client:        client,
		BatchSize:     100, // Large batch so nothing flushes before stop
		FlushInterval: 10 * time.Second,
	})

	ctx := context.Background()
	sink.Start(ctx)

	// Send ops but don't wait for flush
	for i := 0; i < 5; i++ {
		sink.Send(WriteOp{
			Collection: "TestDoc",
			Document:   map[string]any{"index": i},
			Op:         OpCreate,
		})
	}

	// Stop should flush remaining
	sink.Stop()

	if requestCount.Load() != 5 {
		t.Errorf("expected 5 requests after graceful shutdown, got %d", requestCount.Load())
	}
}

func TestSink_ConcurrentSends(t *testing.T) {
	var requestCount atomic.Int32

	server := mockDefraServer(t, func(w http.ResponseWriter, r *http.Request) {
		requestCount.Add(1)

		resp := GQLResponse{
			Data: map[string]any{
				"create_TestDoc": []any{
					map[string]any{"_docID": "doc123"},
				},
			},
		}
		json.NewEncoder(w).Encode(resp)
	})
	defer server.Close()

	client := NewClient(server.URL)
	sink := NewSink(SinkConfig{
		Client:        client,
		BatchSize:     100,
		FlushInterval: 50 * time.Millisecond,
	})

	ctx := context.Background()
	sink.Start(ctx)

	// Send from multiple goroutines
	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			sink.Send(WriteOp{
				Collection: "TestDoc",
				Document:   map[string]any{"index": idx},
				Op:         OpCreate,
			})
		}(i)
	}

	wg.Wait()
	time.Sleep(100 * time.Millisecond)
	sink.Stop()

	if requestCount.Load() != 10 {
		t.Errorf("expected 10 requests, got %d", requestCount.Load())
	}
}

func TestSink_Update(t *testing.T) {
	var requestCount atomic.Int32

	server := mockDefraServer(t, func(w http.ResponseWriter, r *http.Request) {
		requestCount.Add(1)

		resp := GQLResponse{
			Data: map[string]any{
				"update_TestDoc": []any{
					map[string]any{"_docID": "doc123"},
				},
			},
		}
		json.NewEncoder(w).Encode(resp)
	})
	defer server.Close()

	client := NewClient(server.URL)
	sink := NewSink(SinkConfig{
		Client:        client,
		BatchSize:     10,
		FlushInterval: 50 * time.Millisecond,
	})

	ctx := context.Background()
	sink.Start(ctx)
	defer sink.Stop()

	result, err := sink.SendSync(ctx, WriteOp{
		Collection: "TestDoc",
		DocID:      "doc123",
		Document:   map[string]any{"name": "updated"},
		Op:         OpUpdate,
	})

	if err != nil {
		t.Fatalf("SendSync update failed: %v", err)
	}
	if result.DocID != "doc123" {
		t.Errorf("expected docID 'doc123', got %q", result.DocID)
	}
}

func TestSink_Delete(t *testing.T) {
	var requestCount atomic.Int32

	server := mockDefraServer(t, func(w http.ResponseWriter, r *http.Request) {
		requestCount.Add(1)

		resp := GQLResponse{
			Data: map[string]any{
				"delete_TestDoc": []any{
					map[string]any{"_docID": "doc123"},
				},
			},
		}
		json.NewEncoder(w).Encode(resp)
	})
	defer server.Close()

	client := NewClient(server.URL)
	sink := NewSink(SinkConfig{
		Client:        client,
		BatchSize:     10,
		FlushInterval: 50 * time.Millisecond,
	})

	ctx := context.Background()
	sink.Start(ctx)
	defer sink.Stop()

	result, err := sink.SendSync(ctx, WriteOp{
		Collection: "TestDoc",
		DocID:      "doc123",
		Op:         OpDelete,
	})

	if err != nil {
		t.Fatalf("SendSync delete failed: %v", err)
	}
	if result.DocID != "doc123" {
		t.Errorf("expected docID 'doc123', got %q", result.DocID)
	}
}

func TestSink_ManualFlush(t *testing.T) {
	var requestCount atomic.Int32

	server := mockDefraServer(t, func(w http.ResponseWriter, r *http.Request) {
		requestCount.Add(1)

		resp := GQLResponse{
			Data: map[string]any{
				"create_TestDoc": []any{
					map[string]any{"_docID": "doc123"},
				},
			},
		}
		json.NewEncoder(w).Encode(resp)
	})
	defer server.Close()

	client := NewClient(server.URL)
	sink := NewSink(SinkConfig{
		Client:        client,
		BatchSize:     100, // Large batch
		FlushInterval: 10 * time.Second, // Long interval
	})

	ctx := context.Background()
	sink.Start(ctx)
	defer sink.Stop()

	// Send op and wait for it to be queued
	sink.Send(WriteOp{
		Collection: "TestDoc",
		Document:   map[string]any{"name": "test"},
		Op:         OpCreate,
	})

	// Small delay to ensure op is in batch
	time.Sleep(10 * time.Millisecond)

	// Manually flush
	sink.Flush(ctx)

	// Wait for flush to process
	time.Sleep(100 * time.Millisecond)

	if requestCount.Load() != 1 {
		t.Errorf("expected 1 request after manual flush, got %d", requestCount.Load())
	}
}
