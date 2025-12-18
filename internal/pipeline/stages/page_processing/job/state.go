package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
)

// LoadPageState loads existing page state from DefraDB.
func (j *Job) LoadPageState(ctx context.Context) error {
	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}) {
			_docID
			page_num
			ocr_mistral
			ocr_paddle
			ocr_complete
			blend_complete
			label_complete
		}
	}`, j.BookID)

	resp, err := j.DefraClient.Execute(ctx, query, nil)
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

		// Load OCR results dynamically based on configured providers
		for _, provider := range j.OcrProviders {
			field := fmt.Sprintf("ocr_%s", provider)
			if ocrText, ok := page[field].(string); ok && ocrText != "" {
				state.OcrResults[provider] = ocrText
				state.OcrDone[provider] = true
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
	// Check book metadata status
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			metadata_complete
		}
	}`, j.BookID)

	bookResp, err := j.DefraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return err
	}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if book, ok := books[0].(map[string]any); ok {
			if mc, ok := book["metadata_complete"].(bool); ok && mc {
				j.BookState.MetadataComplete = true
				j.BookState.MetadataStarted = true
			}
		}
	}

	// Check ToC status
	tocQuery := fmt.Sprintf(`{
		ToC(filter: {book_id: {_eq: "%s"}}) {
			_docID
			toc_found
			finder_complete
			extract_complete
			start_page
			end_page
		}
	}`, j.BookID)

	tocResp, err := j.DefraClient.Execute(ctx, tocQuery, nil)
	if err == nil {
		if tocs, ok := tocResp.Data["ToC"].([]any); ok && len(tocs) > 0 {
			if toc, ok := tocs[0].(map[string]any); ok {
				if docID, ok := toc["_docID"].(string); ok {
					j.TocDocID = docID
				}
				if finderComplete, ok := toc["finder_complete"].(bool); ok {
					j.BookState.TocFinderDone = finderComplete
					if finderComplete {
						j.BookState.TocFinderStarted = true
					}
				}
				if found, ok := toc["toc_found"].(bool); ok {
					j.BookState.TocFound = found
				}
				if extracted, ok := toc["extract_complete"].(bool); ok {
					j.BookState.TocExtractDone = extracted
					if extracted {
						j.BookState.TocExtractStarted = true
					}
				}
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
func (j *Job) GeneratePageWorkUnits(pageNum int, state *PageState) []jobs.WorkUnit {
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
		unit := j.CreateLabelWorkUnit(pageNum, state)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units
}

// MaybeStartBookOperations checks if we should trigger metadata/ToC operations.
func (j *Job) MaybeStartBookOperations(ctx context.Context) []jobs.WorkUnit {
	labeledCount := j.CountLabeledPages()

	var units []jobs.WorkUnit

	// Start metadata extraction after threshold pages are labeled
	if labeledCount >= LabelThresholdForBookOps && !j.BookState.MetadataStarted {
		unit := j.CreateMetadataWorkUnit(ctx)
		if unit != nil {
			j.BookState.MetadataStarted = true
			units = append(units, *unit)
		}
	}

	// Start ToC finder after threshold pages are labeled
	if labeledCount >= LabelThresholdForBookOps && !j.BookState.TocFinderStarted {
		unit := j.CreateTocFinderWorkUnit(ctx)
		if unit != nil {
			j.BookState.TocFinderStarted = true
			units = append(units, *unit)
		}
	}

	// Start ToC extraction if finder is done and found a ToC
	if j.BookState.TocFinderDone && j.BookState.TocFound && !j.BookState.TocExtractStarted {
		unit := j.CreateTocExtractWorkUnit(ctx)
		if unit != nil {
			j.BookState.TocExtractStarted = true
			units = append(units, *unit)
		}
	}

	return units
}

// CheckCompletion checks if the entire job is complete.
func (j *Job) CheckCompletion() {
	// All pages must be labeled
	if !j.AllPagesComplete() {
		return
	}

	// Metadata must be complete
	if !j.BookState.MetadataComplete {
		return
	}

	// ToC processing must be complete
	// Either: finder done + not found, OR finder done + found + extract done
	if !j.BookState.TocFinderDone {
		return
	}
	if j.BookState.TocFound && !j.BookState.TocExtractDone {
		return
	}

	j.IsDone = true
}
