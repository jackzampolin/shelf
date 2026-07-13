package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
)

// maxConcurrentTocWrites limits concurrent ToC entry DB writes.
const maxConcurrentTocWrites = 5

// tocEntryResult holds the result of a ToC entry persist operation.
type tocEntryResult struct {
	index int
	docID string
	cid   string
	err   error
}

// PersistTocRecord creates the initial ToC record and sets b.tocDocID. Returns DocID.
func (b *BookState) PersistTocRecord(ctx context.Context, doc map[string]any) (string, error) {
	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "ToC",
		Document:   doc,
		Op:         defra.OpCreate,
	})
	if err != nil {
		return "", err
	}

	b.mu.Lock()
	b.tocDocID = result.DocID
	b.tocCID = result.CID
	b.trackCIDLocked("ToC", result.DocID, result.CID)
	b.mu.Unlock()

	return result.DocID, nil
}

// PersistTocFinderResult saves finder result to ToC record.
// Updates b.tocFound, b.tocStartPage, b.tocEndPage.
func (b *BookState) PersistTocFinderResult(ctx context.Context, found bool, startPage, endPage int, fields map[string]any) (string, error) {
	tocDocID := b.TocDocID()
	if tocDocID == "" {
		return "", fmt.Errorf("no ToC doc ID")
	}

	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document:   fields,
		Op:         defra.OpUpdate,
	})
	if err != nil {
		return "", err
	}

	b.mu.Lock()
	b.tocFound = found
	b.tocStartPage = startPage
	b.tocEndPage = endPage
	b.tocCID = result.CID
	b.trackCIDLocked("ToC", tocDocID, result.CID)
	b.mu.Unlock()

	return result.CID, nil
}

// PersistTocExtractComplete marks ToC extraction as complete on the ToC record.
func (b *BookState) PersistTocExtractComplete(ctx context.Context, tocDocID string) (string, error) {
	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	result, err := store.UpdateWithVersion(ctx, "ToC", tocDocID, map[string]any{
		"extract_complete": true,
		"extract_started":  false,
	})
	if err != nil {
		return "", err
	}

	b.mu.Lock()
	b.tocCID = result.CID
	b.trackCIDLocked("ToC", tocDocID, result.CID)
	b.mu.Unlock()

	return result.CID, nil
}
