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

func (m *MemoryStateStore) UpsertWithVersion(_ context.Context, collection string, filter, createInput, updateInput map[string]any) (defra.WriteResult, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	// Check for error injection
	if m.UpsertErr != nil {
		return defra.WriteResult{}, m.UpsertErr
	}
	if m.ErrOnCollection != nil {
		if err, ok := m.ErrOnCollection[collection]; ok {
			return defra.WriteResult{}, err
		}
	}

	// Find existing doc matching filter
	var existingDocID string
	if collDocs := m.docs[collection]; collDocs != nil {
		for docID, doc := range collDocs {
			if m.matchesFilterMap(doc, filter) {
				existingDocID = docID
				break
			}
		}
	}

	// Check docID-level error injection for existing doc
	if existingDocID != "" && m.ErrOnDocID != nil {
		key := collection + ":" + existingDocID
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

	if existingDocID != "" {
		// Update existing - copy updateInput to avoid mutating caller's map
		copiedUpdate := make(map[string]any, len(updateInput))
		for k, v := range updateInput {
			copiedUpdate[k] = v
		}
		op := defra.WriteOp{
			Collection: collection,
			DocID:      existingDocID,
			Document:   copiedUpdate,
			Op:         defra.OpUpdate,
		}
		m.writes = append(m.writes, op)
		m.applyOp(op)
		cid := m.generateCID(collection, existingDocID)
		return defra.WriteResult{DocID: existingDocID, CID: cid}, nil
	}

	// Create new - copy createInput to avoid mutating caller's map
	copiedCreate := make(map[string]any, len(createInput))
	for k, v := range createInput {
		copiedCreate[k] = v
	}
	op := defra.WriteOp{
		Collection: collection,
		Document:   copiedCreate,
		Op:         defra.OpCreate,
	}
	m.writes = append(m.writes, op)
	docID := m.applyOp(op)
	cid := m.generateCID(collection, docID)
	return defra.WriteResult{DocID: docID, CID: cid}, nil
}

func (m *MemoryStateStore) UpdateWithVersion(_ context.Context, collection string, docID string, input map[string]any) (defra.WriteResult, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	// Check for error injection
	if m.UpdateErr != nil {
		return defra.WriteResult{}, m.UpdateErr
	}
	if m.ErrOnCollection != nil {
		if err, ok := m.ErrOnCollection[collection]; ok {
			return defra.WriteResult{}, err
		}
	}
	if m.ErrOnDocID != nil {
		key := collection + ":" + docID
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

	// Copy input to avoid mutating caller's map
	copiedInput := make(map[string]any, len(input))
	for k, v := range input {
		copiedInput[k] = v
	}

	op := defra.WriteOp{
		Collection: collection,
		DocID:      docID,
		Document:   copiedInput,
		Op:         defra.OpUpdate,
	}
	m.writes = append(m.writes, op)
	m.applyOp(op)
	cid := m.generateCID(collection, docID)
	return defra.WriteResult{DocID: docID, CID: cid}, nil
}

// generateCID creates a synthetic CID for tracking in tests.
// Must be called with m.mu held.
func (m *MemoryStateStore) generateCID(collection, docID string) string {
	if m.cidCounter == nil {
		m.cidCounter = make(map[string]int)
	}
	key := collection + ":" + docID
	m.cidCounter[key]++
	return fmt.Sprintf("cid-%s-%s-%d", collection, docID, m.cidCounter[key])
}

// matchesFilterMap checks if a document matches a filter map.
// Must be called with m.mu held.
func (m *MemoryStateStore) matchesFilterMap(doc map[string]any, filter map[string]any) bool {
	for field, value := range filter {
		docVal, ok := doc[field]
		if !ok {
			return false
		}
		// Compare as strings for simplicity
		if fmt.Sprintf("%v", docVal) != fmt.Sprintf("%v", value) {
			return false
		}
	}
	return true
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

// Reset clears all stored data and error injection settings.
func (m *MemoryStateStore) Reset() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.docs = make(map[string]map[string]map[string]any)
	m.autoID = make(map[string]int)
	m.cidCounter = make(map[string]int)
	m.writes = nil
	// Reset error injection
	m.ExecuteErr = nil
	m.SendSyncErr = nil
	m.SendManySyncErr = nil
	m.UpsertErr = nil
	m.UpdateErr = nil
	m.ErrOnCollection = nil
	m.ErrOnDocID = nil
	m.ErrAfterNWrites = 0
	m.errWriteCount = 0
}

// --- Error injection helpers ---

// SetErrorOnCollection configures an error to be returned for operations on a specific collection.
func (m *MemoryStateStore) SetErrorOnCollection(collection string, err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.ErrOnCollection == nil {
		m.ErrOnCollection = make(map[string]error)
	}
	m.ErrOnCollection[collection] = err
}

// SetErrorOnDocID configures an error to be returned for operations on a specific document.
func (m *MemoryStateStore) SetErrorOnDocID(collection, docID string, err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.ErrOnDocID == nil {
		m.ErrOnDocID = make(map[string]error)
	}
	m.ErrOnDocID[collection+":"+docID] = err
}

// SetErrorAfterNWrites configures an error to occur after N successful writes.
// This is useful for testing partial failure scenarios in batch operations.
func (m *MemoryStateStore) SetErrorAfterNWrites(n int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.ErrAfterNWrites = n
	m.errWriteCount = 0
}

// ClearErrors removes all error injection settings.
func (m *MemoryStateStore) ClearErrors() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.ExecuteErr = nil
	m.SendSyncErr = nil
	m.SendManySyncErr = nil
	m.UpsertErr = nil
	m.UpdateErr = nil
	m.ErrOnCollection = nil
	m.ErrOnDocID = nil
	m.ErrAfterNWrites = 0
	m.errWriteCount = 0
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
