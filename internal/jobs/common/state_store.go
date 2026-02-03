package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
)

// StateStore abstracts database operations for BookState persistence.
// This enables unit testing without a live DefraDB instance.
//
// The default implementation (DefraStateStore) delegates to the DefraDB client and sink.
// A MemoryStateStore is provided for unit tests.
type StateStore interface {
	// Execute runs a GraphQL query and returns the response.
	Execute(ctx context.Context, query string, variables map[string]any) (*defra.GQLResponse, error)

	// Send sends a fire-and-forget write operation.
	Send(op defra.WriteOp)

	// SendSync sends a write operation and waits for confirmation.
	SendSync(ctx context.Context, op defra.WriteOp) (defra.WriteResult, error)
}

// DefraStateStore implements StateStore using DefraDB client and sink.
type DefraStateStore struct {
	Client *defra.Client
	Sink   *defra.Sink
}

func (s *DefraStateStore) Execute(ctx context.Context, query string, variables map[string]any) (*defra.GQLResponse, error) {
	return s.Client.Execute(ctx, query, variables)
}

func (s *DefraStateStore) Send(op defra.WriteOp) {
	s.Sink.Send(op)
}

func (s *DefraStateStore) SendSync(ctx context.Context, op defra.WriteOp) (defra.WriteResult, error) {
	return s.Sink.SendSync(ctx, op)
}

// --- Store-based helper functions ---
// These implement common DB operations via the StateStore interface,
// enabling reset hooks and other operations to work with both DefraDB and MemoryStateStore.

// deleteCollectionDocsViaStore queries for documents matching a filter and deletes them.
func deleteCollectionDocsViaStore(ctx context.Context, store StateStore, collection, filterField, filterValue string) error {
	query := fmt.Sprintf(`{
		%s(filter: {%s: {_eq: "%s"}}) {
			_docID
		}
	}`, collection, filterField, filterValue)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query %s for deletion: %w", collection, err)
	}

	docs, ok := resp.Data[collection].([]any)
	if !ok || len(docs) == 0 {
		return nil
	}

	for _, d := range docs {
		doc, ok := d.(map[string]any)
		if !ok {
			continue
		}
		docID, ok := doc["_docID"].(string)
		if !ok || docID == "" {
			continue
		}
		if _, err := store.SendSync(ctx, defra.WriteOp{
			Collection: collection,
			DocID:      docID,
			Op:         defra.OpDelete,
		}); err != nil {
			return fmt.Errorf("failed to delete %s %s: %w", collection, docID, err)
		}
	}
	return nil
}

// updateCollectionDocsViaStore queries for documents matching a filter and updates them.
func updateCollectionDocsViaStore(ctx context.Context, store StateStore, collection, filterField, filterValue string, fields map[string]any) error {
	query := fmt.Sprintf(`{
		%s(filter: {%s: {_eq: "%s"}}) {
			_docID
		}
	}`, collection, filterField, filterValue)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query %s for update: %w", collection, err)
	}

	docs, ok := resp.Data[collection].([]any)
	if !ok || len(docs) == 0 {
		return nil
	}

	for _, d := range docs {
		doc, ok := d.(map[string]any)
		if !ok {
			continue
		}
		docID, ok := doc["_docID"].(string)
		if !ok || docID == "" {
			continue
		}
		if _, err := store.SendSync(ctx, defra.WriteOp{
			Collection: collection,
			DocID:      docID,
			Document:   fields,
			Op:         defra.OpUpdate,
		}); err != nil {
			return fmt.Errorf("failed to update %s %s: %w", collection, docID, err)
		}
	}
	return nil
}
