package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

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
	return OperationState{Status: status, Retries: retries}
}

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
			var started, complete, failed bool
			var retries int
			if ms, ok := book["metadata_started"].(bool); ok {
				started = ms
			}
			if mc, ok := book["metadata_complete"].(bool); ok {
				complete = mc
			}
			if mf, ok := book["metadata_failed"].(bool); ok {
				failed = mf
			}
			if mr, ok := book["metadata_retries"].(float64); ok {
				retries = int(mr)
			}
			j.BookState.Metadata = boolsToOpState(started, complete, failed, retries)
		}
	}

	// Check ToC status via Book relationship (ToC doesn't have book_id field)
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
				start_page
				end_page
			}
		}
	}`, j.BookID)

	tocResp, err := defraClient.Execute(ctx, tocQuery, nil)
	if err == nil {
		if books, ok := tocResp.Data["Book"].([]any); ok && len(books) > 0 {
			if book, ok := books[0].(map[string]any); ok {
				if toc, ok := book["toc"].(map[string]any); ok {
					if docID, ok := toc["_docID"].(string); ok {
						j.TocDocID = docID
					}
					// Finder state
					var fStarted, fComplete, fFailed bool
					var fRetries int
					if fs, ok := toc["finder_started"].(bool); ok {
						fStarted = fs
					}
					if fc, ok := toc["finder_complete"].(bool); ok {
						fComplete = fc
					}
					if ff, ok := toc["finder_failed"].(bool); ok {
						fFailed = ff
					}
					if fr, ok := toc["finder_retries"].(float64); ok {
						fRetries = int(fr)
					}
					j.BookState.TocFinder = boolsToOpState(fStarted, fComplete, fFailed, fRetries)

					if found, ok := toc["toc_found"].(bool); ok {
						j.BookState.TocFound = found
					}

					// Extract state
					var eStarted, eComplete, eFailed bool
					var eRetries int
					if es, ok := toc["extract_started"].(bool); ok {
						eStarted = es
					}
					if ec, ok := toc["extract_complete"].(bool); ok {
						eComplete = ec
					}
					if ef, ok := toc["extract_failed"].(bool); ok {
						eFailed = ef
					}
					if er, ok := toc["extract_retries"].(float64); ok {
						eRetries = int(er)
					}
					j.BookState.TocExtract = boolsToOpState(eStarted, eComplete, eFailed, eRetries)

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
// Must be called with j.mu held.
func (j *Job) MaybeStartBookOperations(ctx context.Context) []jobs.WorkUnit {
	labeledCount := j.CountLabeledPages()

	var units []jobs.WorkUnit

	// Start metadata extraction after threshold pages are labeled
	if labeledCount >= LabelThresholdForBookOps && j.BookState.Metadata.CanStart() {
		unit := j.CreateMetadataWorkUnit(ctx)
		if unit != nil {
			if err := j.BookState.Metadata.Start(); err == nil {
				if err := j.PersistMetadataState(ctx); err != nil {
					j.BookState.Metadata.Status = OpNotStarted // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			}
		}
	}

	// Start ToC finder after threshold pages are labeled AND first 30 pages have OCR.
	// Consecutive check ensures pages 1-30 all have blend_complete before ToC finder starts,
	// since ToC is typically in the first 20-30 pages.
	if labeledCount >= LabelThresholdForBookOps && j.ConsecutiveFrontMatterComplete() && j.BookState.TocFinder.CanStart() {
		unit := j.CreateTocFinderWorkUnit(ctx)
		if unit != nil {
			if err := j.BookState.TocFinder.Start(); err == nil {
				if err := j.PersistTocFinderState(ctx); err != nil {
					j.BookState.TocFinder.Status = OpNotStarted // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			}
		}
	}

	// Start ToC extraction if finder is done and found a ToC
	if j.BookState.TocFinder.IsDone() && j.BookState.TocFound && j.BookState.TocExtract.CanStart() {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Info("attempting to create ToC extract work unit",
				"toc_start_page", j.BookState.TocStartPage,
				"toc_end_page", j.BookState.TocEndPage,
				"toc_doc_id", j.TocDocID)
		}
		unit := j.CreateTocExtractWorkUnit(ctx)
		if unit != nil {
			if err := j.BookState.TocExtract.Start(); err == nil {
				if err := j.PersistTocExtractState(ctx); err != nil {
					j.BookState.TocExtract.Status = OpNotStarted // Rollback on failure
				} else {
					units = append(units, *unit)
				}
			}
		} else if logger != nil {
			logger.Warn("failed to create ToC extract work unit",
				"toc_start_page", j.BookState.TocStartPage,
				"toc_end_page", j.BookState.TocEndPage)
		}
	}

	return units
}

// CheckCompletion checks if the entire job is complete.
// A job is complete when all pages are labeled AND book-level operations
// are either complete or permanently failed.
func (j *Job) CheckCompletion(ctx context.Context) {
	// All pages must be labeled
	if !j.AllPagesComplete() {
		return
	}

	// Metadata must be complete or permanently failed
	if !j.BookState.Metadata.IsDone() {
		return
	}

	// ToC finder must be complete or permanently failed
	if !j.BookState.TocFinder.IsDone() {
		return
	}

	// If ToC was found, extraction must also be done
	if j.BookState.TocFound && !j.BookState.TocExtract.IsDone() {
		return
	}

	j.IsDone = true

	// Persist the complete status to DefraDB
	j.PersistBookStatus(ctx, BookStatusComplete)
}

// PersistBookStatus persists book status to DefraDB.
func (j *Job) PersistBookStatus(ctx context.Context, status BookStatus) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Fire-and-forget - no need to block
	sink.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      j.BookID,
		Document: map[string]any{
			"status": string(status),
		},
		Op: defra.OpUpdate,
	})
	return nil
}

// PersistMetadataState persists metadata state to DefraDB.
func (j *Job) PersistMetadataState(ctx context.Context) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Fire-and-forget - no need to block
	sink.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      j.BookID,
		Document: map[string]any{
			"metadata_started": j.BookState.Metadata.IsStarted(),
			"metadata_failed":  j.BookState.Metadata.IsFailed(),
			"metadata_retries": j.BookState.Metadata.Retries,
		},
		Op: defra.OpUpdate,
	})
	return nil
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

	// Fire-and-forget - no need to block
	sink.Send(defra.WriteOp{
		Collection: "ToC",
		DocID:      j.TocDocID,
		Document: map[string]any{
			"finder_started": j.BookState.TocFinder.IsStarted(),
			"finder_failed":  j.BookState.TocFinder.IsFailed(),
			"finder_retries": j.BookState.TocFinder.Retries,
		},
		Op: defra.OpUpdate,
	})
	return nil
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

	// Fire-and-forget - no need to block
	sink.Send(defra.WriteOp{
		Collection: "ToC",
		DocID:      j.TocDocID,
		Document: map[string]any{
			"extract_started": j.BookState.TocExtract.IsStarted(),
			"extract_failed":  j.BookState.TocExtract.IsFailed(),
			"extract_retries": j.BookState.TocExtract.Retries,
		},
		Op: defra.OpUpdate,
	})
	return nil
}
