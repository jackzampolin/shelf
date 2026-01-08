package job

import (
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// MaxRetries is the maximum number of retries for LLM operations.
const MaxRetries = 3

// Phase constants.
const (
	PhaseBuild    = "build"
	PhaseExtract  = "extract"
	PhaseClassify = "classify"
	PhasePolish   = "polish"
	PhaseFinalize = "finalize"
)

// WorkUnitType constants for LLM work units.
// Note: Extract phase runs synchronously (no work units needed for text processing).
const (
	WorkUnitTypeClassify = "classify_matter"
	WorkUnitTypePolish   = "polish_chapter"
)

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	UnitType   string
	Phase      string
	ChapterID  string // entry_id for extract/polish phases
	RetryCount int
}

// Job runs common-structure processing for a book.
// Requires finalize_toc to be complete.
type Job struct {
	common.TrackedBaseJob[WorkUnitInfo]

	// ToC reference
	TocDocID string

	// Phase tracking
	CurrentPhase string

	// Build phase output
	Chapters []*ChapterState

	// Extract phase tracking
	ChaptersToExtract  int
	ChaptersExtracted  int
	ExtractsFailed     int

	// Classify phase tracking
	ClassifyPending bool
	Classifications map[string]string // entry_id -> matter_type

	// Polish phase tracking
	ChaptersToPolish int
	ChaptersPolished int
	PolishFailed     int

	// Linked entries (loaded at start, from finalize_toc)
	LinkedEntries []*LinkedTocEntry
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
func NewFromLoadResult(result *common.LoadBookResult, linkedEntries []*LinkedTocEntry) *Job {
	return &Job{
		TrackedBaseJob:  common.NewTrackedBaseJob[WorkUnitInfo](result.Book),
		TocDocID:        result.TocDocID,
		CurrentPhase:    PhaseBuild,
		LinkedEntries:   linkedEntries,
		Chapters:        make([]*ChapterState, 0),
		Classifications: make(map[string]string),
	}
}

// Type returns the job type identifier.
func (j *Job) Type() string {
	return "common-structure"
}

// MetricsFor returns base metrics attribution for this job.
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return j.BaseJob.MetricsFor(j.Type())
}

// LinkedTocEntry is an alias to common.LinkedTocEntry for use in this package.
type LinkedTocEntry = common.LinkedTocEntry

// ChapterState tracks chapter during processing.
type ChapterState struct {
	// Identity
	EntryID string // Unique within book (e.g., "ch_001")
	DocID   string // DefraDB doc ID (after create)

	// From ToC
	Title       string
	Level       int
	LevelName   string
	EntryNumber string
	SortOrder   int
	Source      string // "toc", "heading", "reconciled"
	TocEntryID  string // Link back to original TocEntry

	// Page boundaries
	StartPage int
	EndPage   int

	// Hierarchy
	ParentID string // entry_id of parent chapter

	// Matter classification (set in classify phase)
	MatterType string // "front_matter", "body", "back_matter"

	// Text content (set in extract phase)
	RawPageTexts   []PageText
	MechanicalText string
	PageBreaks     []int

	// Polished text (set in polish phase)
	PolishedText string
	EditsApplied []TextEdit
	WordCount    int

	// Paragraphs (created from text)
	Paragraphs []*ParagraphState

	// Processing state
	ExtractDone bool
	PolishDone  bool
}

// PageText holds text from a single page.
type PageText struct {
	ScanPage        int
	PrintedPage     *string
	RawText         string
	CleanedText     string
	RunningHeader   *string
	PageNumberLabel *string
}

// ParagraphState tracks paragraph during processing.
type ParagraphState struct {
	SortOrder    int
	StartPage    int
	RawText      string
	PolishedText string
	WordCount    int
	EditsApplied []TextEdit
}

// TextEdit represents an edit from LLM polish.
type TextEdit struct {
	OldText string `json:"old_text"`
	NewText string `json:"new_text"`
	Reason  string `json:"reason"`
}

// ClassifyResult represents the LLM classification response.
type ClassifyResult struct {
	Classifications map[string]string `json:"classifications"`
}

// PolishResult represents the LLM polish response.
type PolishResult struct {
	Edits []TextEdit `json:"edits"`
}
