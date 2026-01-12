package job

import (
	"fmt"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/types"
)

// MaxRetries is the maximum number of retries for finalize ToC operations.
const MaxRetries = 3

// Phase constants.
const (
	PhasePattern  = "pattern"
	PhaseDiscover = "discover"
	PhaseValidate = "validate"
)

// WorkUnitType constants.
const (
	WorkUnitTypePattern  = "pattern_analysis"
	WorkUnitTypeDiscover = "discover_entry"
	WorkUnitTypeGap      = "gap_investigation"
)

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	UnitType   string
	Phase      string
	EntryKey   string // For discover phase: identifier like "chapter_14"
	GapKey     string // For validate phase: "gap_100_150"
	RetryCount int
}

// Job runs ToC finalization for a book.
// Requires link_toc to be complete (TocEntry records have actual_page links).
type Job struct {
	common.TrackedBaseJob[WorkUnitInfo]

	// ToC reference
	TocDocID string

	// Phase tracking
	CurrentPhase string

	// Pattern analysis results
	PatternResult *PatternResult

	// Page pattern context (loaded from page pattern analysis and labels)
	PagePatternCtx *PagePatternContext

	// Discover phase state
	EntriesToFind    []*EntryToFind
	DiscoverAgents   map[string]*agent.Agent // entryKey -> agent
	EntriesComplete  int
	EntriesFound     int

	// Validate phase state
	Gaps         []*Gap
	GapAgents    map[string]*agent.Agent // gapKey -> agent
	GapsComplete int
	GapsFixes    int

	// Linked entries (loaded at start)
	LinkedEntries []*LinkedTocEntry
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
func NewFromLoadResult(result *common.LoadBookResult, linkedEntries []*LinkedTocEntry) *Job {
	// Build PagePatternContext from page pattern analysis if available
	pagePatternCtx := buildPagePatternContext(result.Book)

	// Set body range: prefer page pattern analysis, fall back to ToC entries, then full book
	if pagePatternCtx.HasBoundaries {
		// Use accurate body boundaries from page pattern analysis
		result.Book.BodyStart = pagePatternCtx.BodyStartPage
		result.Book.BodyEnd = pagePatternCtx.BodyEndPage
	} else {
		// Compute body range from linked entries (min/max of actual_page)
		var minPage, maxPage int
		for _, entry := range linkedEntries {
			if entry.ActualPage != nil {
				page := *entry.ActualPage
				if minPage == 0 || page < minPage {
					minPage = page
				}
				if page > maxPage {
					maxPage = page
				}
			}
		}
		if minPage > 0 && maxPage > 0 {
			result.Book.BodyStart = minPage
			result.Book.BodyEnd = maxPage
		} else {
			// Fallback to full book range
			result.Book.BodyStart = 1
			result.Book.BodyEnd = result.Book.TotalPages
		}
	}

	return &Job{
		TrackedBaseJob: common.NewTrackedBaseJob[WorkUnitInfo](result.Book),
		TocDocID:       result.TocDocID,
		CurrentPhase:   PhasePattern,
		PagePatternCtx: &pagePatternCtx,
		LinkedEntries:  linkedEntries,
		DiscoverAgents: make(map[string]*agent.Agent),
		GapAgents:      make(map[string]*agent.Agent),
	}
}

// buildPagePatternContext extracts pattern context from page pattern analysis results.
func buildPagePatternContext(book *common.BookState) PagePatternContext {
	ctx := PagePatternContext{}

	// Extract body boundaries and chapter patterns from page pattern analysis
	if book.PatternAnalysisResult != nil {
		par := book.PatternAnalysisResult

		// Body boundaries
		if par.BodyBoundaries != nil {
			ctx.BodyStartPage = par.BodyBoundaries.BodyStartPage
			if par.BodyBoundaries.BodyEndPage != nil {
				ctx.BodyEndPage = *par.BodyBoundaries.BodyEndPage
			} else {
				ctx.BodyEndPage = book.TotalPages
			}
			ctx.HasBoundaries = true
		}

		// Chapter patterns from running header clusters
		for _, cp := range par.ChapterPatterns {
			detected := types.DetectedChapter{
				PageNum:       cp.StartPage,
				RunningHeader: cp.RunningHeader,
				ChapterTitle:  cp.ChapterTitle,
				ChapterNumber: cp.ChapterNumber,
				Source:        types.SourcePatternAnalysis,
				Confidence:    types.ParseConfidenceLevel(cp.Confidence),
			}
			ctx.ChapterPatterns = append(ctx.ChapterPatterns, detected)
		}
	}

	return ctx
}

// Type returns the job type identifier.
func (j *Job) Type() string {
	return "finalize-toc"
}

// MetricsFor returns base metrics attribution for this job.
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return j.BaseJob.MetricsFor(j.Type())
}

// LinkedTocEntry is an alias to common.LinkedTocEntry for use in this package.
type LinkedTocEntry = common.LinkedTocEntry

// PatternResult holds the results of pattern analysis.
type PatternResult struct {
	Patterns  []DiscoveredPattern `json:"patterns"`
	Excluded  []ExcludedRange     `json:"excluded_ranges"`
	Reasoning string              `json:"reasoning"`
}

// DiscoveredPattern represents a chapter sequence to discover.
type DiscoveredPattern struct {
	PatternType   string `json:"pattern_type"`   // "sequential" or "named"
	LevelName     string `json:"level_name"`     // "chapter", "part", "section"
	HeadingFormat string `json:"heading_format"` // "Chapter {n}", "{n}", "CHAPTER {n}"
	RangeStart    string `json:"range_start"`    // "1", "I", "A"
	RangeEnd      string `json:"range_end"`      // "38", "X", "F"
	Level         int    `json:"level"`          // Structural depth: 1=part, 2=chapter, 3=section
	Reasoning     string `json:"reasoning"`
}

// ExcludedRange represents a page range to skip during discovery.
type ExcludedRange struct {
	StartPage int    `json:"start_page"`
	EndPage   int    `json:"end_page"`
	Reason    string `json:"reason"` // "back_matter", "front_matter", "bibliography", etc.
}

// EntryToFind represents a missing chapter/section to discover.
type EntryToFind struct {
	Key              string `json:"key"`               // Unique key like "chapter_14"
	LevelName        string `json:"level_name"`        // "chapter", "part"
	Identifier       string `json:"identifier"`        // "14", "III", "A"
	HeadingFormat    string `json:"heading_format"`    // "Chapter {n}"
	Level            int    `json:"level"`
	ExpectedNearPage int    `json:"expected_near_page"` // Estimated page based on sequence
	SearchRangeStart int    `json:"search_range_start"`
	SearchRangeEnd   int    `json:"search_range_end"`
}

// Gap represents a gap in page coverage between entries.
type Gap struct {
	Key            string `json:"key"`              // Unique key like "gap_100_150"
	StartPage      int    `json:"start_page"`
	EndPage        int    `json:"end_page"`
	Size           int    `json:"size"`
	PrevEntryTitle string `json:"prev_entry_title"`
	PrevEntryPage  int    `json:"prev_entry_page"`
	NextEntryTitle string `json:"next_entry_title"`
	NextEntryPage  int    `json:"next_entry_page"`
}

// GapFix represents a fix suggestion for a gap.
type GapFix struct {
	FixType   string // "add_entry", "correct_entry", "no_fix_needed", "flag_for_review"
	ScanPage  int
	Title     string
	Level     int
	LevelName string
	EntryDocID string // For corrections
	Reasoning string
	Flagged   bool
}

// CandidateHeading represents a heading detected in the book but not in ToC.
type CandidateHeading struct {
	PageNum int
	Text    string
	Level   int
}

// PagePatternContext holds page pattern analysis data for enhanced ToC finalization.
type PagePatternContext struct {
	// Body boundaries from page pattern analysis
	BodyStartPage int
	BodyEndPage   int
	HasBoundaries bool

	// Detected chapters from running header clusters
	// Uses types.DetectedChapter for consistency across packages
	ChapterPatterns []types.DetectedChapter

	// Pages marked as chapter starts from labeling
	ChapterStartPages []int
}

// Validate checks that the PagePatternContext has valid values.
func (ctx *PagePatternContext) Validate() error {
	if ctx.HasBoundaries {
		if ctx.BodyStartPage <= 0 || ctx.BodyEndPage <= 0 {
			return fmt.Errorf("page boundaries must be positive when HasBoundaries is true")
		}
		if ctx.BodyStartPage > ctx.BodyEndPage {
			return fmt.Errorf("BodyStartPage (%d) cannot exceed BodyEndPage (%d)", ctx.BodyStartPage, ctx.BodyEndPage)
		}
	}
	return nil
}
