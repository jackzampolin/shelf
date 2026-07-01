package common

import (
	"fmt"
	"regexp"

	"github.com/jackzampolin/shelf/internal/defra"
)

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
