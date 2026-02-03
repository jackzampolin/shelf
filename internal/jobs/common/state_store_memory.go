package common

import (
	"context"
	"fmt"
	"regexp"
	"strings"
	"sync"

	"github.com/jackzampolin/shelf/internal/defra"
)

// MemoryStateStore implements StateStore with in-memory storage for unit tests.
// It stores documents as map[string]any keyed by collection and docID.
// It supports basic GraphQL filter queries for _docID and field equality.
type MemoryStateStore struct {
	mu sync.RWMutex

	// docs maps collection -> docID -> document fields
	docs map[string]map[string]map[string]any

	// autoID tracks the next auto-generated doc ID per collection
	autoID map[string]int

	// writes tracks all write operations for test assertions
	writes []defra.WriteOp
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

	collection, filters := parseSimpleQuery(query)
	if collection == "" {
		return &defra.GQLResponse{Data: map[string]any{}}, nil
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
	m.writes = append(m.writes, op)
	docID := m.applyOp(op)
	return defra.WriteResult{DocID: docID}, nil
}

// applyOp applies a write operation to the in-memory store.
// Must be called with m.mu held.
func (m *MemoryStateStore) applyOp(op defra.WriteOp) string {
	if m.docs[op.Collection] == nil {
		m.docs[op.Collection] = make(map[string]map[string]any)
	}

	switch op.Op {
	case defra.OpCreate:
		m.autoID[op.Collection]++
		docID := op.DocID
		if docID == "" {
			docID = fmt.Sprintf("auto-%s-%d", op.Collection, m.autoID[op.Collection])
		}
		doc := make(map[string]any, len(op.Document))
		for k, v := range op.Document {
			doc[k] = v
		}
		m.docs[op.Collection][docID] = doc
		return docID

	case defra.OpUpdate:
		if op.DocID == "" {
			return ""
		}
		existing := m.docs[op.Collection][op.DocID]
		if existing == nil {
			existing = make(map[string]any)
			m.docs[op.Collection][op.DocID] = existing
		}
		for k, v := range op.Document {
			if v == nil {
				delete(existing, k)
			} else {
				existing[k] = v
			}
		}
		return op.DocID

	case defra.OpDelete:
		if op.DocID != "" {
			delete(m.docs[op.Collection], op.DocID)
		}
		return op.DocID
	}

	return ""
}

// --- Test helper methods ---

// GetDoc returns a document from the store for test assertions.
func (m *MemoryStateStore) GetDoc(collection, docID string) map[string]any {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if m.docs[collection] == nil {
		return nil
	}
	return m.docs[collection][docID]
}

// SetDoc directly sets a document in the store for test setup.
func (m *MemoryStateStore) SetDoc(collection, docID string, doc map[string]any) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.docs[collection] == nil {
		m.docs[collection] = make(map[string]map[string]any)
	}
	m.docs[collection][docID] = doc
}

// WriteCount returns the number of write operations recorded.
func (m *MemoryStateStore) WriteCount() int {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return len(m.writes)
}

// GetWrites returns all recorded write operations.
func (m *MemoryStateStore) GetWrites() []defra.WriteOp {
	m.mu.RLock()
	defer m.mu.RUnlock()
	result := make([]defra.WriteOp, len(m.writes))
	copy(result, m.writes)
	return result
}

// --- Simple query parser ---
// Handles patterns like: { Collection(filter: {field: {_eq: "value"}}) { ... } }

var (
	collectionRe = regexp.MustCompile(`\{\s*(\w+)\s*(?:\(|{)`)
	filterRe     = regexp.MustCompile(`(\w+)\s*:\s*\{\s*_eq\s*:\s*"([^"]*)"`)
)

type filterCondition struct {
	field string
	value string
}

func parseSimpleQuery(query string) (collection string, filters []filterCondition) {
	// Extract collection name
	match := collectionRe.FindStringSubmatch(query)
	if len(match) < 2 {
		return "", nil
	}
	collection = match[1]

	// Extract filter conditions
	filterMatches := filterRe.FindAllStringSubmatch(query, -1)
	for _, fm := range filterMatches {
		if len(fm) >= 3 {
			filters = append(filters, filterCondition{field: fm[1], value: fm[2]})
		}
	}

	return collection, filters
}

func matchesFilters(doc map[string]any, docID string, filters []filterCondition) bool {
	for _, f := range filters {
		if f.field == "_docID" {
			if docID != f.value {
				return false
			}
			continue
		}
		val, ok := doc[f.field]
		if !ok {
			return false
		}
		// Compare as string
		valStr := fmt.Sprintf("%v", val)
		if valStr != f.value {
			return false
		}
	}
	return true
}

// matchesBoolFilter checks if a bool field matches a filter value string.
func matchesBoolFilter(val any, filterValue string) bool {
	boolVal, ok := val.(bool)
	if !ok {
		return false
	}
	return (boolVal && filterValue == "true") || (!boolVal && filterValue == "false")
}

// --- Relationship support ---
// The memory store supports a simple relationship convention:
// If a query contains "toc { ... }", it looks for a "toc" field in the document
// that references another document.

// SetRelation sets a relationship between two documents for test setup.
// This stores the related document's data inline, mimicking DefraDB's relationship queries.
func (m *MemoryStateStore) SetRelation(collection, docID, field string, relatedData map[string]any) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.docs[collection] == nil {
		m.docs[collection] = make(map[string]map[string]any)
	}
	if m.docs[collection][docID] == nil {
		m.docs[collection][docID] = make(map[string]any)
	}
	m.docs[collection][docID][field] = relatedData
}

// --- Convenience methods for common test patterns ---

// SetBookDoc creates a Book document with standard fields for testing.
func (m *MemoryStateStore) SetBookDoc(bookID string, fields map[string]any) {
	m.SetDoc("Book", bookID, fields)
}

// SetTocDoc creates a ToC document with standard fields for testing.
func (m *MemoryStateStore) SetTocDoc(tocDocID string, fields map[string]any) {
	m.SetDoc("ToC", tocDocID, fields)
}

// SetPageDoc creates a Page document for testing.
func (m *MemoryStateStore) SetPageDoc(docID string, fields map[string]any) {
	m.SetDoc("Page", docID, fields)
}

// Reset clears all stored data.
func (m *MemoryStateStore) Reset() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.docs = make(map[string]map[string]map[string]any)
	m.autoID = make(map[string]int)
	m.writes = nil
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
