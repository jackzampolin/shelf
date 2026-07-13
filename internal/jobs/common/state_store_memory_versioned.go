package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
)

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
