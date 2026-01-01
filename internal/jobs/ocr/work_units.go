package ocr

import (
	"github.com/jackzampolin/shelf/internal/jobs"
)

// CreateOcrWorkUnit creates an OCR work unit for a page and provider.
func (j *Job) CreateOcrWorkUnit(pageNum int, provider string) *jobs.WorkUnit {
	return CreateOcrWorkUnitFunc(
		OcrWorkUnitParams{
			HomeDir:  j.HomeDir,
			BookID:   j.BookID,
			JobID:    j.RecordID,
			PageNum:  pageNum,
			Provider: provider,
			Stage:    JobType,
		},
		func(unitID string) {
			j.RegisterWorkUnit(unitID, WorkUnitInfo{
				PageNum:  pageNum,
				Provider: provider,
				UnitType: "ocr",
			})
		},
	)
}

// RegisterWorkUnit registers a pending work unit.
func (j *Job) RegisterWorkUnit(unitID string, info WorkUnitInfo) {
	j.PendingUnits[unitID] = info
}

// GetWorkUnit gets a pending work unit without removing it.
func (j *Job) GetWorkUnit(unitID string) (WorkUnitInfo, bool) {
	info, ok := j.PendingUnits[unitID]
	return info, ok
}

// RemoveWorkUnit removes a pending work unit.
func (j *Job) RemoveWorkUnit(unitID string) {
	delete(j.PendingUnits, unitID)
}

// GenerateAllWorkUnits creates work units for all pages.
// If a page needs extraction, creates extract work unit (OCR follows after extraction).
// If a page already has an image, creates OCR work units directly.
func (j *Job) GenerateAllWorkUnits() []jobs.WorkUnit {
	var units []jobs.WorkUnit

	for pageNum := 1; pageNum <= j.TotalPages; pageNum++ {
		state := j.PageState[pageNum]
		if state == nil {
			continue
		}

		// Check if page needs extraction first
		if j.NeedsExtraction(pageNum) {
			if unit := j.CreateExtractWorkUnit(pageNum); unit != nil {
				units = append(units, *unit)
			}
			continue // OCR work units will be created after extraction completes
		}

		// Image exists - create OCR work units for providers that haven't completed
		for _, provider := range j.OcrProviders {
			if !state.OcrDone[provider] {
				if unit := j.CreateOcrWorkUnit(pageNum, provider); unit != nil {
					units = append(units, *unit)
				}
			}
		}
	}

	return units
}
