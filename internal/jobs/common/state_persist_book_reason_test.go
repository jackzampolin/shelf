package common

import (
	"context"
	"testing"
)

func TestPersistBookStatusWithReason(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	b := NewBookState("book-1")
	b.Store = store

	if _, err := b.PersistBookStatusWithReason(context.Background(), "failed", "finalize context limit"); err != nil {
		t.Fatalf("PersistBookStatusWithReason error: %v", err)
	}

	doc := store.GetDoc("Book", "book-1")
	if doc["status"] != "failed" {
		t.Fatalf("status = %v, want failed", doc["status"])
	}
	if doc["status_reason"] != "finalize context limit" {
		t.Fatalf("status_reason = %v, want 'finalize context limit'", doc["status_reason"])
	}
}

func TestPersistBookStatusClearsStaleReason(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{"status": "failed", "status_reason": "old failure"})

	b := NewBookState("book-1")
	b.Store = store

	if _, err := b.PersistBookStatus(context.Background(), "complete"); err != nil {
		t.Fatalf("PersistBookStatus error: %v", err)
	}

	doc := store.GetDoc("Book", "book-1")
	if doc["status"] != "complete" {
		t.Fatalf("status = %v, want complete", doc["status"])
	}
	if doc["status_reason"] != "" {
		t.Fatalf("status_reason = %v, want empty (cleared)", doc["status_reason"])
	}
}

func TestPersistBookStatusHelperClearsStaleReason(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{"status": "failed", "status_reason": "old failure"})

	b := NewBookState("book-1")
	b.Store = store

	if _, err := PersistBookStatus(context.Background(), b, "processing"); err != nil {
		t.Fatalf("PersistBookStatus helper error: %v", err)
	}

	doc := store.GetDoc("Book", "book-1")
	if doc["status"] != "processing" {
		t.Fatalf("status = %v, want processing", doc["status"])
	}
	if doc["status_reason"] != "" {
		t.Fatalf("status_reason = %v, want empty (cleared)", doc["status_reason"])
	}
}
