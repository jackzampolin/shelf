package defra

import (
	"context"
	"fmt"
)

// CreateWithVersion creates a document and returns DocID + commit CIDs.
func (c *Client) CreateWithVersion(ctx context.Context, collection string, input map[string]any) (WriteResult, error) {
	inputGQL, err := mapToGraphQLInput(input)
	if err != nil {
		return WriteResult{}, fmt.Errorf("failed to build input: %w", err)
	}
	query := fmt.Sprintf(`mutation { add_%s(input: %s) { _docID _version { cid } } }`, collection, inputGQL)

	resp, err := c.Execute(ctx, query, nil)
	if err != nil {
		return WriteResult{}, err
	}
	if errMsg := resp.Error(); errMsg != "" {
		return WriteResult{}, fmt.Errorf("create error: %s", errMsg)
	}

	createKey := fmt.Sprintf("add_%s", collection)
	if docs, ok := resp.Data[createKey].([]any); ok && len(docs) > 0 {
		if doc, ok := docs[0].(map[string]any); ok {
			result := WriteResult{}
			if docID, ok := doc["_docID"].(string); ok {
				result.DocID = docID
			}
			if cids := extractVersionCIDs(doc); len(cids) > 0 {
				result.CIDs = cids
				result.CID = cids[0]
			}
			return result, nil
		}
	}

	return WriteResult{}, fmt.Errorf("unexpected response format: %+v", resp.Data)
}

// UpdateWithVersion updates a document and returns DocID + commit CIDs.
func (c *Client) UpdateWithVersion(ctx context.Context, collection string, docID string, input map[string]any) (WriteResult, error) {
	inputGQL, err := mapToGraphQLInput(input)
	if err != nil {
		return WriteResult{}, fmt.Errorf("failed to build input: %w", err)
	}
	query := fmt.Sprintf(`mutation { update_%s(docID: %q, input: %s) { _docID _version { cid } } }`, collection, docID, inputGQL)

	resp, err := c.Execute(ctx, query, nil)
	if err != nil {
		return WriteResult{}, err
	}
	if errMsg := resp.Error(); errMsg != "" {
		return WriteResult{}, fmt.Errorf("update error: %s", errMsg)
	}

	updateKey := fmt.Sprintf("update_%s", collection)
	if docs, ok := resp.Data[updateKey].([]any); ok && len(docs) > 0 {
		if doc, ok := docs[0].(map[string]any); ok {
			result := WriteResult{DocID: docID}
			if docIDResp, ok := doc["_docID"].(string); ok && docIDResp != "" {
				result.DocID = docIDResp
			}
			if cids := extractVersionCIDs(doc); len(cids) > 0 {
				result.CIDs = cids
				result.CID = cids[0]
			}
			return result, nil
		}
	}

	return WriteResult{DocID: docID}, nil
}

// UpsertWithVersion creates or updates a document and returns DocID + commit CIDs.
func (c *Client) UpsertWithVersion(ctx context.Context, collection string, filter, createInput, updateInput map[string]any) (WriteResult, error) {
	filterGQL, err := mapToGraphQLFilter(filter)
	if err != nil {
		return WriteResult{}, fmt.Errorf("failed to build filter: %w", err)
	}
	createGQL, err := mapToGraphQLInput(createInput)
	if err != nil {
		return WriteResult{}, fmt.Errorf("failed to build create input: %w", err)
	}
	updateGQL, err := mapToGraphQLInput(updateInput)
	if err != nil {
		return WriteResult{}, fmt.Errorf("failed to build update input: %w", err)
	}

	// DefraDB v1.0 renamed the upsert "create" argument to "add".
	// IMPORTANT: do NOT select `_version { cid }` in an upsert_ mutation. In
	// DefraDB v1.0.0-rc1 the upsert planner re-runs its result Select inside the
	// still-open write transaction; selecting the commit DAG (_version) then
	// deadlocks reading the just-written merkle-clock heads — the request hangs
	// and the client times out. Select only _docID here, then read the CID
	// separately (a write-txn-free query). add_/update_ are unaffected.
	query := fmt.Sprintf(`mutation { upsert_%s(filter: %s, add: %s, update: %s) { _docID } }`,
		collection, filterGQL, createGQL, updateGQL)

	resp, err := c.Execute(ctx, query, nil)
	if err != nil {
		return WriteResult{}, err
	}
	if errMsg := resp.Error(); errMsg != "" {
		return WriteResult{}, fmt.Errorf("upsert error: %s", errMsg)
	}

	upsertKey := fmt.Sprintf("upsert_%s", collection)
	docs, ok := resp.Data[upsertKey].([]any)
	if !ok || len(docs) == 0 {
		return WriteResult{}, fmt.Errorf("unexpected response format: %+v", resp.Data)
	}
	doc, ok := docs[0].(map[string]any)
	if !ok {
		return WriteResult{}, fmt.Errorf("unexpected response format: %+v", resp.Data)
	}

	result := WriteResult{}
	if docID, ok := doc["_docID"].(string); ok {
		result.DocID = docID
	}
	// Best-effort CID fetch via a separate read; the upsert already succeeded.
	if result.DocID != "" {
		if cids := c.fetchVersionCIDs(ctx, collection, result.DocID); len(cids) > 0 {
			result.CIDs = cids
			result.CID = cids[0]
		}
	}
	return result, nil
}

// fetchVersionCIDs reads a document's commit CIDs via a separate query. Used
// after upsert, where selecting _version inside the mutation deadlocks v1.0.
func (c *Client) fetchVersionCIDs(ctx context.Context, collection, docID string) []string {
	query := fmt.Sprintf(`{ %s(filter: {_docID: {_eq: %q}}) { _version { cid } } }`, collection, docID)
	resp, err := c.Execute(ctx, query, nil)
	if err != nil || resp.Error() != "" {
		return nil
	}
	if docs, ok := resp.Data[collection].([]any); ok && len(docs) > 0 {
		if doc, ok := docs[0].(map[string]any); ok {
			return extractVersionCIDs(doc)
		}
	}
	return nil
}

// mapToGraphQLFilter renders a simple equality-filter map as a DefraDB filter
// argument. DefraDB v1.0 requires the operator form {field: {_eq: value}} and
// rejects the old shorthand {field: value}. Values that are already operator
// blocks (maps) are passed through unchanged.
func mapToGraphQLFilter(filter map[string]any) (string, error) {
	eqFilter := make(map[string]any, len(filter))
	for k, v := range filter {
		if _, ok := v.(map[string]any); ok {
			eqFilter[k] = v
		} else {
			eqFilter[k] = map[string]any{"_eq": v}
		}
	}
	return mapToGraphQLInput(eqFilter)
}
