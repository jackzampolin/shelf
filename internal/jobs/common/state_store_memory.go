package common

import (
	"context"
	"fmt"
	"strings"
	"sync"

	"github.com/jackzampolin/shelf/internal/defra"
)

// MemoryStateStore implements StateStore with in-memory storage for unit tests.
// It stores documents as map[string]any keyed by collection and docID.
// It supports basic GraphQL filter queries for _docID and field equality.
// Error injection is supported for testing error handling paths.
type MemoryStateStore struct {
	mu sync.RWMutex

	// docs maps collection -> docID -> document fields
	docs map[string]map[string]map[string]any

	// autoID tracks the next auto-generated doc ID per collection
	autoID map[string]int

	// cidCounter tracks CID generation per collection:docID for version tracking
	cidCounter map[string]int

	// writes tracks all write operations for test assertions
	writes []defra.WriteOp

	// --- Error injection fields for testing ---
	// Set these to trigger errors from specific operations

	// ExecuteErr is returned by Execute when non-nil
	ExecuteErr error

	// SendSyncErr is returned by SendSync when non-nil
	SendSyncErr error

	// SendManySyncErr is returned by SendManySync when non-nil
	SendManySyncErr error

	// UpsertErr is returned by UpsertWithVersion when non-nil
	UpsertErr error

	// UpdateErr is returned by UpdateWithVersion when non-nil
	UpdateErr error

	// ErrOnCollection causes operations on specific collections to fail
	// Key is collection name, value is the error to return
	ErrOnCollection map[string]error

	// ErrOnDocID causes operations on specific docIDs to fail
	// Key is "collection:docID", value is the error to return
	ErrOnDocID map[string]error

	// ErrAfterNWrites causes an error after N successful writes
	// Used to test partial failure scenarios
	ErrAfterNWrites int
	errWriteCount   int
}

// NewMemoryStateStore creates an empty in-memory state store.
func NewMemoryStateStore() *MemoryStateStore {
	return &MemoryStateStore{
		docs:   make(map[string]map[string]map[string]any),
		autoID: make(map[string]int),
	}
}

func (m *MemoryStateStore) Execute(_ context.Context, query string, _ map[string]any) (*defra.GQLResponse, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	// Check for error injection
	if m.ExecuteErr != nil {
		return nil, m.ExecuteErr
	}

	collection, filters := parseSimpleQuery(query)
	if collection == "" {
		return &defra.GQLResponse{Data: map[string]any{}}, nil
	}

	// Check collection-level error injection
	if m.ErrOnCollection != nil {
		if err, ok := m.ErrOnCollection[collection]; ok {
			return nil, err
		}
	}

	collDocs := m.docs[collection]
	if collDocs == nil {
		return &defra.GQLResponse{Data: map[string]any{collection: []any{}}}, nil
	}

	var results []any
	for docID, doc := range collDocs {
		if matchesFilters(doc, docID, filters) {
			// Return a copy with _docID included
			copied := make(map[string]any, len(doc)+1)
			for k, v := range doc {
				copied[k] = v
			}
			copied["_docID"] = docID
			results = append(results, copied)
		}
	}

	return &defra.GQLResponse{Data: map[string]any{collection: results}}, nil
}

func (m *MemoryStateStore) Send(op defra.WriteOp) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.writes = append(m.writes, op)
	m.applyOp(op)
}

func (m *MemoryStateStore) SendSync(_ context.Context, op defra.WriteOp) (defra.WriteResult, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	// Check for error injection
	if m.SendSyncErr != nil {
		return defra.WriteResult{}, m.SendSyncErr
	}
	if m.ErrOnCollection != nil {
		if err, ok := m.ErrOnCollection[op.Collection]; ok {
			return defra.WriteResult{}, err
		}
	}
	if m.ErrOnDocID != nil && op.DocID != "" {
		key := op.Collection + ":" + op.DocID
		if err, ok := m.ErrOnDocID[key]; ok {
			return defra.WriteResult{}, err
		}
	}
	// Check ErrAfterNWrites
	if m.ErrAfterNWrites > 0 {
		m.errWriteCount++
		if m.errWriteCount > m.ErrAfterNWrites {
			return defra.WriteResult{}, fmt.Errorf("injected error after %d writes", m.ErrAfterNWrites)
		}
	}

	m.writes = append(m.writes, op)
	docID := m.applyOp(op)
	cid := m.generateCID(op.Collection, docID)
	return defra.WriteResult{DocID: docID, CID: cid}, nil
}

func (m *MemoryStateStore) SendManySync(_ context.Context, ops []defra.WriteOp) ([]defra.WriteResult, error) {
	if len(ops) == 0 {
		return nil, nil
	}
	m.mu.Lock()
	defer m.mu.Unlock()

	// Check for global error injection
	if m.SendManySyncErr != nil {
		return nil, m.SendManySyncErr
	}

	results := make([]defra.WriteResult, len(ops))
	for i, op := range ops {
		// Check collection-level error injection
		if m.ErrOnCollection != nil {
			if err, ok := m.ErrOnCollection[op.Collection]; ok {
				results[i] = defra.WriteResult{Err: err}
				continue
			}
		}
		// Check docID-level error injection
		if m.ErrOnDocID != nil && op.DocID != "" {
			key := op.Collection + ":" + op.DocID
			if err, ok := m.ErrOnDocID[key]; ok {
				results[i] = defra.WriteResult{Err: err}
				continue
			}
		}
		// Check ErrAfterNWrites
		if m.ErrAfterNWrites > 0 {
			m.errWriteCount++
			if m.errWriteCount > m.ErrAfterNWrites {
				results[i] = defra.WriteResult{Err: fmt.Errorf("injected error after %d writes", m.ErrAfterNWrites)}
				continue
			}
		}

		m.writes = append(m.writes, op)
		docID := m.applyOp(op)
		cid := m.generateCID(op.Collection, docID)
		results[i] = defra.WriteResult{DocID: docID, CID: cid}
	}
	return results, nil
}

// String returns a debug representation of the store contents.
func (m *MemoryStateStore) String() string {
	m.mu.RLock()
	defer m.mu.RUnlock()

	var sb strings.Builder
	for collection, docs := range m.docs {
		sb.WriteString(fmt.Sprintf("%s (%d docs):\n", collection, len(docs)))
		for docID, doc := range docs {
			sb.WriteString(fmt.Sprintf("  %s: %v\n", docID, doc))
		}
	}
	return sb.String()
}
