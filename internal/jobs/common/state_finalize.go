package common

// --- Finalize ToC State Types ---

// FinalizePatternResult holds the results of ToC pattern analysis.
type FinalizePatternResult struct {
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
	Key              string `json:"key"`            // Unique key like "chapter_14"
	LevelName        string `json:"level_name"`     // "chapter", "part"
	Identifier       string `json:"identifier"`     // "14", "III", "A"
	HeadingFormat    string `json:"heading_format"` // "Chapter {n}"
	Level            int    `json:"level"`
	ExpectedNearPage int    `json:"expected_near_page"` // Estimated page based on sequence
	SearchRangeStart int    `json:"search_range_start"`
	SearchRangeEnd   int    `json:"search_range_end"`
}

// FinalizeGap represents a gap in page coverage between entries.
type FinalizeGap struct {
	Key            string `json:"key"` // Unique key like "gap_100_150"
	StartPage      int    `json:"start_page"`
	EndPage        int    `json:"end_page"`
	Size           int    `json:"size"`
	PrevEntryTitle string `json:"prev_entry_title"`
	PrevEntryPage  int    `json:"prev_entry_page"`
	NextEntryTitle string `json:"next_entry_title"`
	NextEntryPage  int    `json:"next_entry_page"`
}

// --- Finalize State Accessors ---

// FinalizeState holds finalize ToC sub-job state within BookState.
type FinalizeState struct {
	Phase           string                 `json:"phase"` // pattern, discover, validate
	PatternResult   *FinalizePatternResult `json:"pattern_result"`
	EntriesToFind   []*EntryToFind         `json:"entries_to_find"`
	EntriesComplete int                    `json:"entries_complete"`
	EntriesFound    int                    `json:"entries_found"`
	Gaps            []*FinalizeGap         `json:"gaps"`
	GapsComplete    int                    `json:"gaps_complete"`
	GapsFixes       int                    `json:"gaps_fixes"`
}

// GetFinalizePhase returns the current finalize phase (thread-safe).
func (b *BookState) GetFinalizePhase() string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.finalizePhase
}

// SetFinalizePhase sets the current finalize phase (thread-safe).
func (b *BookState) SetFinalizePhase(phase string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizePhase = phase
}

// GetFinalizePatternResult returns the finalize pattern result (thread-safe).
func (b *BookState) GetFinalizePatternResult() *FinalizePatternResult {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.finalizePatternResult
}

// SetFinalizePatternResult sets the finalize pattern result (thread-safe).
func (b *BookState) SetFinalizePatternResult(result *FinalizePatternResult) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizePatternResult = result
}

// GetEntriesToFind returns entries to find in discover phase (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetEntriesToFind() []*EntryToFind {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.entriesToFind == nil {
		return nil
	}
	result := make([]*EntryToFind, len(b.entriesToFind))
	copy(result, b.entriesToFind)
	return result
}

// SetEntriesToFind sets entries to find in discover phase (thread-safe).
func (b *BookState) SetEntriesToFind(entries []*EntryToFind) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.entriesToFind = entries
}

// AppendEntryToFind adds an entry to find (thread-safe).
func (b *BookState) AppendEntryToFind(entry *EntryToFind) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.entriesToFind = append(b.entriesToFind, entry)
}

// GetEntriesToFindCount returns the number of entries to find (thread-safe).
func (b *BookState) GetEntriesToFindCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.entriesToFind)
}

// GetFinalizeGaps returns gaps to investigate (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetFinalizeGaps() []*FinalizeGap {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.finalizeGaps == nil {
		return nil
	}
	result := make([]*FinalizeGap, len(b.finalizeGaps))
	copy(result, b.finalizeGaps)
	return result
}

// SetFinalizeGaps sets gaps to investigate (thread-safe).
func (b *BookState) SetFinalizeGaps(gaps []*FinalizeGap) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeGaps = gaps
}

// AppendFinalizeGap adds a gap to investigate (thread-safe).
func (b *BookState) AppendFinalizeGap(gap *FinalizeGap) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeGaps = append(b.finalizeGaps, gap)
}

// GetFinalizeGapsCount returns the number of gaps to investigate (thread-safe).
func (b *BookState) GetFinalizeGapsCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.finalizeGaps)
}

// GetFinalizeProgress returns finalize progress counters (thread-safe).
func (b *BookState) GetFinalizeProgress() (entriesComplete, entriesFound, gapsComplete, gapsFixes int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.finalizeEntriesComplete, b.finalizeEntriesFound, b.finalizeGapsComplete, b.finalizeGapsFixes
}

// SetFinalizeProgress sets finalize progress counters (thread-safe).
func (b *BookState) SetFinalizeProgress(entriesComplete, entriesFound, gapsComplete, gapsFixes int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeEntriesComplete = entriesComplete
	b.finalizeEntriesFound = entriesFound
	b.finalizeGapsComplete = gapsComplete
	b.finalizeGapsFixes = gapsFixes
}

// GetFinalizeEntriesTotalCount returns the total number of entries to find (thread-safe).
func (b *BookState) GetFinalizeEntriesTotalCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.finalizeEntriesTotal
}

// SetFinalizeEntriesTotal sets the total number of entries to find (thread-safe).
func (b *BookState) SetFinalizeEntriesTotal(total int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeEntriesTotal = total
}

// GetFinalizeGapsTotalCount returns the total number of gaps to investigate (thread-safe).
func (b *BookState) GetFinalizeGapsTotalCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.finalizeGapsTotal
}

// SetFinalizeGapsTotal sets the total number of gaps to investigate (thread-safe).
func (b *BookState) SetFinalizeGapsTotal(total int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeGapsTotal = total
}

// IncrementFinalizeEntriesComplete increments entries complete (thread-safe).
func (b *BookState) IncrementFinalizeEntriesComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeEntriesComplete++
}

// IncrementFinalizeEntriesFound increments entries found (thread-safe).
func (b *BookState) IncrementFinalizeEntriesFound() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeEntriesFound++
}

// IncrementFinalizeGapsComplete increments gaps complete (thread-safe).
func (b *BookState) IncrementFinalizeGapsComplete() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeGapsComplete++
}

// IncrementFinalizeGapsFixes increments gaps fixed (thread-safe).
func (b *BookState) IncrementFinalizeGapsFixes() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizeGapsFixes++
}

// --- Page Pattern Context ---

// PagePatternContext holds page pattern analysis data for enhanced ToC finalization.
// This is populated from PagePatternResult during finalize phase.
type PagePatternContext struct {
	BodyStartPage   int
	BodyEndPage     int
	HasBoundaries   bool
	ChapterPatterns []DetectedChapter
}

// DetectedChapter represents a chapter detected by pattern analysis.
type DetectedChapter struct {
	PageNum       int
	RunningHeader string
	ChapterTitle  string
	ChapterNumber string
	Source        string // "pattern_analysis", "label", etc.
	Confidence    string // "high", "medium", "low"
}

// GetFinalizePagePatternCtx returns the page pattern context for finalize phase (thread-safe).
func (b *BookState) GetFinalizePagePatternCtx() *PagePatternContext {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.finalizePagePatternCtx
}

// SetFinalizePagePatternCtx sets the page pattern context for finalize phase (thread-safe).
func (b *BookState) SetFinalizePagePatternCtx(ctx *PagePatternContext) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.finalizePagePatternCtx = ctx
}
