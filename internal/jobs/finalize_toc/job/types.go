package job

import (
	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
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
	// Compute body range from linked entries (min/max of actual_page)
	// This is the page range where ToC entries are linked
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
	// Set body range on BookState for pattern analysis
	if minPage > 0 && maxPage > 0 {
		result.Book.BodyStart = minPage
		result.Book.BodyEnd = maxPage
	}

	return &Job{
		TrackedBaseJob: common.NewTrackedBaseJob[WorkUnitInfo](result.Book),
		TocDocID:       result.TocDocID,
		CurrentPhase:   PhasePattern,
		LinkedEntries:  linkedEntries,
		DiscoverAgents: make(map[string]*agent.Agent),
		GapAgents:      make(map[string]*agent.Agent),
	}
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
	Patterns []DiscoveredPattern
	Excluded []ExcludedRange
	Reasoning string
}

// DiscoveredPattern represents a chapter sequence to discover.
type DiscoveredPattern struct {
	PatternType   string // "sequential" or "named"
	LevelName     string // "chapter", "part", "section"
	HeadingFormat string // "Chapter {n}", "{n}", "CHAPTER {n}"
	RangeStart    string // "1", "I", "A"
	RangeEnd      string // "38", "X", "F"
	Level         int    // Structural depth: 1=part, 2=chapter, 3=section
	Reasoning     string
}

// ExcludedRange represents a page range to skip during discovery.
type ExcludedRange struct {
	StartPage int
	EndPage   int
	Reason    string // "back_matter", "front_matter", "bibliography", etc.
}

// EntryToFind represents a missing chapter/section to discover.
type EntryToFind struct {
	Key              string // Unique key like "chapter_14"
	LevelName        string // "chapter", "part"
	Identifier       string // "14", "III", "A"
	HeadingFormat    string // "Chapter {n}"
	Level            int
	ExpectedNearPage int    // Estimated page based on sequence
	SearchRangeStart int
	SearchRangeEnd   int
}

// Gap represents a gap in page coverage between entries.
type Gap struct {
	Key            string // Unique key like "gap_100_150"
	StartPage      int
	EndPage        int
	Size           int
	PrevEntryTitle string
	PrevEntryPage  int
	NextEntryTitle string
	NextEntryPage  int
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
