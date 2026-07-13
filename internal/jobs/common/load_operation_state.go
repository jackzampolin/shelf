package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/svcctx"
)

// loadOpStateFromData reads the 4 standard operation fields from a data map and sets the state.
// The prefix is the DB field prefix (e.g. "metadata", "finder", "extract").
func loadOpStateFromData(book *BookState, op OpType, data map[string]any, prefix string) {
	var started, complete, failed bool
	var retries int
	if v, ok := data[prefix+"_started"].(bool); ok {
		started = v
	}
	if v, ok := data[prefix+"_complete"].(bool); ok {
		complete = v
	}
	if v, ok := data[prefix+"_failed"].(bool); ok {
		failed = v
	}
	if v, ok := data[prefix+"_retries"].(float64); ok {
		retries = int(v)
	}
	book.SetOpState(op, started, complete, failed, retries)
}

// boolsToOpState converts DB boolean fields to OperationState.
func boolsToOpState(started, complete, failed bool, retries int) OperationState {
	var status OpStatus
	switch {
	case failed:
		status = OpFailed
	case complete:
		status = OpComplete
	case started:
		status = OpInProgress
	default:
		status = OpNotStarted
	}
	return NewOperationState(status, retries)
}

// LoadBookOperationState loads book-level operation state from DefraDB.
// Returns the ToC document ID if found.
func LoadBookOperationState(ctx context.Context, book *BookState) (tocDocID string, err error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return "", fmt.Errorf("defra client not in context")
	}

	// Check book metadata, pattern analysis, and structure status
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			metadata_started
			metadata_complete
			metadata_failed
			metadata_retries
			structure_started
			structure_complete
			structure_failed
			structure_retries
			structure_phase
			structure_chapters_total
			structure_chapters_extracted
			structure_chapters_polished
			structure_polish_failed
		}
	}`, book.BookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return "", err
	}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if bookData, ok := books[0].(map[string]any); ok {
			// Load Book-collection operation states via registry
			loadOpStateFromData(book, OpMetadata, bookData, "metadata")
			loadOpStateFromData(book, OpStructure, bookData, "structure")

			// Structure phase tracking
			if sp, ok := bookData["structure_phase"].(string); ok {
				book.structurePhase = sp
			}
			if sct, ok := bookData["structure_chapters_total"].(float64); ok {
				book.structureChaptersTotal = int(sct)
			}
			if sce, ok := bookData["structure_chapters_extracted"].(float64); ok {
				book.structureChaptersExtracted = int(sce)
			}
			if scp, ok := bookData["structure_chapters_polished"].(float64); ok {
				book.structureChaptersPolished = int(scp)
			}
			if spf, ok := bookData["structure_polish_failed"].(float64); ok {
				book.structurePolishFailed = int(spf)
			}
		}
	}

	// Check ToC status via Book relationship (ToC doesn't have book_id field)
	// Note: _version { cid } omitted — DefraDB 500s on empty nested relationships.
	// ToC CIDs are captured at write time via SendTracked/TrackWrite.
	tocQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			toc {
				_docID
				toc_found
				finder_started
				finder_complete
				finder_failed
				finder_retries
				extract_started
				extract_complete
				extract_failed
				extract_retries
				link_started
				link_complete
				link_failed
				link_retries
				finalize_started
				finalize_complete
				finalize_failed
				finalize_retries
				start_page
				end_page
			}
		}
	}`, book.BookID)

	tocResp, err := defraClient.Execute(ctx, tocQuery, nil)
	if err != nil {
		// ToC query errors are not fatal, but log them for debugging
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Warn("ToC query failed, proceeding without ToC state",
				"book_id", book.BookID,
				"error", err)
		}
		return "", nil
	}

	if books, ok := tocResp.Data["Book"].([]any); ok && len(books) > 0 {
		if bookData, ok := books[0].(map[string]any); ok {
			if toc, ok := bookData["toc"].(map[string]any); ok {
				if docID, ok := toc["_docID"].(string); ok {
					tocDocID = docID
				}
				// Load ToC-collection operation states via registry
				loadOpStateFromData(book, OpTocFinder, toc, "finder")
				loadOpStateFromData(book, OpTocExtract, toc, "extract")
				loadOpStateFromData(book, OpTocLink, toc, "link")
				loadOpStateFromData(book, OpTocFinalize, toc, "finalize")

				if found, ok := toc["toc_found"].(bool); ok {
					book.tocFound = found
				}

				// Page range
				if sp, ok := toc["start_page"].(float64); ok {
					book.tocStartPage = int(sp)
				}
				if ep, ok := toc["end_page"].(float64); ok {
					book.tocEndPage = int(ep)
				}
			}
		}
	}

	// Store tocDocID on the book so OpConfig.DocIDSource can access it
	book.SetTocDocID(tocDocID)

	return tocDocID, nil
}
