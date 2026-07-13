package common

import (
	"github.com/jackzampolin/shelf/internal/defra"
)

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
