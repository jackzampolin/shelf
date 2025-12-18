package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
)

// checkCancelled returns an error if the context is cancelled.
func checkCancelled(ctx context.Context) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
		return nil
	}
}

func (j *Job) ID() string {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	return j.RecordID
}

func (j *Job) SetRecordID(id string) {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	j.RecordID = id
}

func (j *Job) Type() string {
	return "page-processing"
}

func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	// Check for cancellation
	if err := checkCancelled(ctx); err != nil {
		return nil, err
	}

	// Load existing page state from DefraDB
	if err := j.LoadPageState(ctx); err != nil {
		return nil, fmt.Errorf("failed to load page state: %w", err)
	}

	// Load book-level state
	if err := j.LoadBookState(ctx); err != nil {
		return nil, fmt.Errorf("failed to load book state: %w", err)
	}

	// Generate work units for incomplete pages
	var units []jobs.WorkUnit

	for pageNum := 1; pageNum <= j.TotalPages; pageNum++ {
		// Check for cancellation periodically in the loop
		if err := checkCancelled(ctx); err != nil {
			return nil, err
		}

		state := j.PageState[pageNum]
		if state == nil {
			// Create page record and state
			state = NewPageState()
			j.PageState[pageNum] = state

			// Create Page record in DefraDB
			docID, err := j.DefraClient.Create(ctx, "Page", map[string]any{
				"book_id":        j.BookID,
				"page_num":       pageNum,
				"ocr_complete":   false,
				"blend_complete": false,
				"label_complete": false,
			})
			if err != nil {
				return nil, fmt.Errorf("failed to create page record: %w", err)
			}
			state.PageDocID = docID
		}

		// Check what work is needed for this page
		newUnits := j.GeneratePageWorkUnits(pageNum, state)
		units = append(units, newUnits...)
	}

	// Check if we should start book-level operations
	bookUnits := j.MaybeStartBookOperations(ctx)
	units = append(units, bookUnits...)

	return units, nil
}

func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	// Check for cancellation
	if err := checkCancelled(ctx); err != nil {
		return nil, err
	}

	info, ok := j.GetAndRemoveWorkUnit(result.WorkUnitID)
	if !ok {
		return nil, nil // Not our work unit
	}

	if !result.Success {
		return nil, fmt.Errorf("work unit failed (%s): %v", info.UnitType, result.Error)
	}

	var newUnits []jobs.WorkUnit

	switch info.UnitType {
	case "ocr":
		units, err := j.HandleOcrComplete(ctx, info, result)
		if err != nil {
			return nil, err
		}
		newUnits = append(newUnits, units...)

	case "blend":
		units, err := j.HandleBlendComplete(ctx, info, result)
		if err != nil {
			return nil, err
		}
		newUnits = append(newUnits, units...)

	case "label":
		units, err := j.HandleLabelComplete(ctx, info, result)
		if err != nil {
			return nil, err
		}
		newUnits = append(newUnits, units...)

	case "metadata":
		if err := j.HandleMetadataComplete(ctx, result); err != nil {
			return nil, err
		}

	case "toc_finder":
		units, err := j.HandleTocFinderComplete(ctx, result)
		if err != nil {
			return nil, err
		}
		newUnits = append(newUnits, units...)

	case "toc_extract":
		if err := j.HandleTocExtractComplete(ctx, result); err != nil {
			return nil, err
		}
	}

	// Check overall completion
	j.CheckCompletion()

	return newUnits, nil
}

func (j *Job) Done() bool {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	return j.IsDone
}

func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	ocrDone, blendDone, labelDone := 0, 0, 0
	for _, state := range j.PageState {
		allOcr := true
		for _, provider := range j.OcrProviders {
			if !state.OcrDone[provider] {
				allOcr = false
				break
			}
		}
		if allOcr {
			ocrDone++
		}
		if state.BlendDone {
			blendDone++
		}
		if state.LabelDone {
			labelDone++
		}
	}

	return map[string]string{
		"book_id":            j.BookID,
		"total_pages":        fmt.Sprintf("%d", j.TotalPages),
		"ocr_complete":       fmt.Sprintf("%d", ocrDone),
		"blend_complete":     fmt.Sprintf("%d", blendDone),
		"label_complete":     fmt.Sprintf("%d", labelDone),
		"metadata_started":   fmt.Sprintf("%v", j.BookState.MetadataStarted),
		"metadata_complete":  fmt.Sprintf("%v", j.BookState.MetadataComplete),
		"toc_finder_started": fmt.Sprintf("%v", j.BookState.TocFinderStarted),
		"toc_found":          fmt.Sprintf("%v", j.BookState.TocFound),
		"toc_extract_done":   fmt.Sprintf("%v", j.BookState.TocExtractDone),
		"done":               fmt.Sprintf("%v", j.IsDone),
	}, nil
}

func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	return j.ProviderProgress()
}
