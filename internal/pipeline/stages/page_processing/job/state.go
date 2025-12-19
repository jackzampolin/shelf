package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// LoadPageState loads existing page state from DefraDB.
func (j *Job) LoadPageState(ctx context.Context) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	// Query pages with their related OCR results
	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}) {
			_docID
			page_num
			extract_complete
			blend_complete
			label_complete
			ocr_results {
				provider
				text
			}
		}
	}`, j.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return err
	}

	if errMsg := resp.Error(); errMsg != "" {
		return fmt.Errorf("query error: %s", errMsg)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil // No pages yet
	}

	for _, p := range pages {
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}

		pageNum := 0
		if pn, ok := page["page_num"].(float64); ok {
			pageNum = int(pn)
		}
		if pageNum == 0 {
			continue
		}

		state := NewPageState()

		if docID, ok := page["_docID"].(string); ok {
			state.PageDocID = docID
		}
		if extractComplete, ok := page["extract_complete"].(bool); ok {
			state.ExtractDone = extractComplete
		}

		// Load OCR results from the relationship
		if ocrResults, ok := page["ocr_results"].([]any); ok {
			for _, r := range ocrResults {
				result, ok := r.(map[string]any)
				if !ok {
					continue
				}
				provider, _ := result["provider"].(string)
				text, _ := result["text"].(string)
				if provider != "" && text != "" {
					state.OcrResults[provider] = text
					state.OcrDone[provider] = true
				}
			}
		}

		if blendComplete, ok := page["blend_complete"].(bool); ok {
			state.BlendDone = blendComplete
		}
		if labelComplete, ok := page["label_complete"].(bool); ok {
			state.LabelDone = labelComplete
		}

		j.PageState[pageNum] = state
	}

	return nil
}

// LoadBookState loads book-level processing state from DefraDB.
func (j *Job) LoadBookState(ctx context.Context) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	// Check book metadata status
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			metadata_started
			metadata_complete
			metadata_failed
			metadata_retries
		}
	}`, j.BookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return err
	}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if book, ok := books[0].(map[string]any); ok {
			if ms, ok := book["metadata_started"].(bool); ok {
				j.BookState.MetadataStarted = ms
			}
			if mc, ok := book["metadata_complete"].(bool); ok {
				j.BookState.MetadataComplete = mc
			}
			if mf, ok := book["metadata_failed"].(bool); ok {
				j.BookState.MetadataFailed = mf
			}
			if mr, ok := book["metadata_retries"].(float64); ok {
				j.BookState.MetadataRetries = int(mr)
			}
		}
	}

	// Check ToC status
	tocQuery := fmt.Sprintf(`{
		ToC(filter: {book_id: {_eq: "%s"}}) {
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
			start_page
			end_page
		}
	}`, j.BookID)

	tocResp, err := defraClient.Execute(ctx, tocQuery, nil)
	if err == nil {
		if tocs, ok := tocResp.Data["ToC"].([]any); ok && len(tocs) > 0 {
			if toc, ok := tocs[0].(map[string]any); ok {
				if docID, ok := toc["_docID"].(string); ok {
					j.TocDocID = docID
				}
				// Finder state
				if fs, ok := toc["finder_started"].(bool); ok {
					j.BookState.TocFinderStarted = fs
				}
				if fc, ok := toc["finder_complete"].(bool); ok {
					j.BookState.TocFinderDone = fc
				}
				if ff, ok := toc["finder_failed"].(bool); ok {
					j.BookState.TocFinderFailed = ff
				}
				if fr, ok := toc["finder_retries"].(float64); ok {
					j.BookState.TocFinderRetries = int(fr)
				}
				if found, ok := toc["toc_found"].(bool); ok {
					j.BookState.TocFound = found
				}
				// Extract state
				if es, ok := toc["extract_started"].(bool); ok {
					j.BookState.TocExtractStarted = es
				}
				if ec, ok := toc["extract_complete"].(bool); ok {
					j.BookState.TocExtractDone = ec
				}
				if ef, ok := toc["extract_failed"].(bool); ok {
					j.BookState.TocExtractFailed = ef
				}
				if er, ok := toc["extract_retries"].(float64); ok {
					j.BookState.TocExtractRetries = int(er)
				}
				// Page range
				if sp, ok := toc["start_page"].(float64); ok {
					j.BookState.TocStartPage = int(sp)
				}
				if ep, ok := toc["end_page"].(float64); ok {
					j.BookState.TocEndPage = int(ep)
				}
			}
		}
	}

	return nil
}

// GeneratePageWorkUnits creates work units for a page based on its current state.
// Must be called with j.Mu held.
func (j *Job) GeneratePageWorkUnits(ctx context.Context, pageNum int, state *PageState) []jobs.WorkUnit {
	var units []jobs.WorkUnit

	// Check if OCR is needed
	allOcrDone := true
	for _, provider := range j.OcrProviders {
		if !state.OcrDone[provider] {
			allOcrDone = false
			unit := j.CreateOcrWorkUnit(pageNum, provider)
			if unit != nil {
				units = append(units, *unit)
			}
		}
	}

	// If all OCR done but blend not done, create blend unit
	if allOcrDone && !state.BlendDone {
		unit := j.CreateBlendWorkUnit(pageNum, state)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	// If blend done but label not done, create label unit
	if state.BlendDone && !state.LabelDone {
		unit := j.CreateLabelWorkUnit(ctx, pageNum, state)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units
}

// MaybeStartBookOperations checks if we should trigger metadata/ToC operations.
// Must be called with j.Mu held.
func (j *Job) MaybeStartBookOperations(ctx context.Context) []jobs.WorkUnit {
	labeledCount := j.CountLabeledPages()

	var units []jobs.WorkUnit

	// Start metadata extraction after threshold pages are labeled
	// Skip if already started, completed, or permanently failed
	if labeledCount >= LabelThresholdForBookOps &&
		!j.BookState.MetadataStarted &&
		!j.BookState.MetadataComplete &&
		!j.BookState.MetadataFailed {
		unit := j.CreateMetadataWorkUnit(ctx)
		if unit != nil {
			// Persist first, then update memory (crash-safe ordering)
			j.BookState.MetadataStarted = true
			if err := j.PersistMetadataState(ctx); err != nil {
				j.BookState.MetadataStarted = false // Rollback on failure
			} else {
				units = append(units, *unit)
			}
		}
	}

	// Start ToC finder after threshold pages are labeled
	// Skip if already started, done, or permanently failed
	if labeledCount >= LabelThresholdForBookOps &&
		!j.BookState.TocFinderStarted &&
		!j.BookState.TocFinderDone &&
		!j.BookState.TocFinderFailed {
		unit := j.CreateTocFinderWorkUnit(ctx)
		if unit != nil {
			// Persist first, then update memory (crash-safe ordering)
			j.BookState.TocFinderStarted = true
			if err := j.PersistTocFinderState(ctx); err != nil {
				j.BookState.TocFinderStarted = false // Rollback on failure
			} else {
				units = append(units, *unit)
			}
		}
	}

	// Start ToC extraction if finder is done and found a ToC
	// Skip if already started, done, or permanently failed
	if j.BookState.TocFinderDone && j.BookState.TocFound &&
		!j.BookState.TocExtractStarted &&
		!j.BookState.TocExtractDone &&
		!j.BookState.TocExtractFailed {
		unit := j.CreateTocExtractWorkUnit(ctx)
		if unit != nil {
			// Persist first, then update memory (crash-safe ordering)
			j.BookState.TocExtractStarted = true
			if err := j.PersistTocExtractState(ctx); err != nil {
				j.BookState.TocExtractStarted = false // Rollback on failure
			} else {
				units = append(units, *unit)
			}
		}
	}

	return units
}

// CheckCompletion checks if the entire job is complete.
// A job is complete when all pages are labeled AND book-level operations
// are either complete or permanently failed.
func (j *Job) CheckCompletion() {
	// All pages must be labeled
	if !j.AllPagesComplete() {
		return
	}

	// Metadata must be complete or permanently failed
	metadataDone := j.BookState.MetadataComplete || j.BookState.MetadataFailed
	if !metadataDone {
		return
	}

	// ToC processing must be complete or permanently failed
	// Either: finder done/failed + not found, OR finder done/failed + found + extract done/failed
	tocFinderDone := j.BookState.TocFinderDone || j.BookState.TocFinderFailed
	if !tocFinderDone {
		return
	}
	tocExtractDone := j.BookState.TocExtractDone || j.BookState.TocExtractFailed
	if j.BookState.TocFound && !tocExtractDone {
		return
	}

	j.IsDone = true
}

// PersistMetadataState persists metadata state to DefraDB.
func (j *Job) PersistMetadataState(ctx context.Context) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	_, err := sink.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      j.BookID,
		Document: map[string]any{
			"metadata_started": j.BookState.MetadataStarted,
			"metadata_failed":  j.BookState.MetadataFailed,
			"metadata_retries": j.BookState.MetadataRetries,
		},
		Op: defra.OpUpdate,
	})
	return err
}

// PersistTocFinderState persists ToC finder state to DefraDB.
func (j *Job) PersistTocFinderState(ctx context.Context) error {
	if j.TocDocID == "" {
		return nil // No ToC record yet
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	_, err := sink.SendSync(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      j.TocDocID,
		Document: map[string]any{
			"finder_started": j.BookState.TocFinderStarted,
			"finder_failed":  j.BookState.TocFinderFailed,
			"finder_retries": j.BookState.TocFinderRetries,
		},
		Op: defra.OpUpdate,
	})
	return err
}

// PersistTocExtractState persists ToC extract state to DefraDB.
func (j *Job) PersistTocExtractState(ctx context.Context) error {
	if j.TocDocID == "" {
		return nil // No ToC record yet
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	_, err := sink.SendSync(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      j.TocDocID,
		Document: map[string]any{
			"extract_started": j.BookState.TocExtractStarted,
			"extract_failed":  j.BookState.TocExtractFailed,
			"extract_retries": j.BookState.TocExtractRetries,
		},
		Op: defra.OpUpdate,
	})
	return err
}
