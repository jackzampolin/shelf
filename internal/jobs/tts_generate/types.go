package tts_generate

import (
	"strings"
	"sync"

	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs"
)

// Work unit type constants.
const (
	WorkUnitTypeTTSSegment    = "tts_segment"
	WorkUnitTypeConcatenate   = "concatenate"
	WorkUnitTypeChapterFinish = "chapter_finish"
)

// Chapter represents a chapter with polished text ready for TTS.
type Chapter struct {
	DocID        string
	EntryID      string
	Title        string
	Level        int
	LevelName    string
	EntryNumber  string
	MatterType   string
	PolishedText string
	SortOrder    int
	ChapterIdx   int

	// Parsed paragraphs
	Paragraphs []string
}

// BookAudioRecord represents the stored BookAudio record.
type BookAudioRecord struct {
	ID            string
	Status        string
	Provider      string
	Voice         string
	Format        string
	TotalDuration int
	ChapterCount  int
	SegmentCount  int
	TotalChars    int
	TotalCost     float64
}

// SegmentResult holds the result of a TTS segment generation.
type SegmentResult struct {
	DocID         string
	DurationMS    int
	StartOffsetMS int
	AudioFile     string
	CostUSD       float64
	CharCount     int
}

// ChapterProgress tracks progress for a single chapter.
type ChapterProgress struct {
	ChapterIdx       int
	TotalSegments    int
	CompletedSegments int
	Segments         map[int]*SegmentResult // paragraphIdx -> result
	TotalDurationMS  int
	TotalCostUSD     float64
	AudioFile        string // concatenated chapter audio
	ChapterAudioID   string // DefraDB record ID
}

// AudioState holds the complete state for TTS generation.
type AudioState struct {
	mu sync.Mutex

	BookID      string
	Title       string
	Author      string
	Chapters    []*Chapter
	TTSProvider string
	Voice       string
	Format      string
	HomeDir     *home.Dir

	// Existing record (if resuming)
	BookAudioID string

	// Progress tracking per chapter
	ChapterProgress map[int]*ChapterProgress

	// Totals
	TotalSegments     int
	CompletedSegments int
	TotalCostUSD      float64
	TotalDurationMS   int
}

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	UnitType     string // tts_segment, concatenate, chapter_finish
	ChapterIdx   int
	ParagraphIdx int
	RetryCount   int
}

// Job implements the TTS generation job.
type Job struct {
	mu       sync.Mutex
	recordID string
	isDone   bool

	State   *AudioState
	Tracker *WorkUnitTracker
}

// WorkUnitTracker tracks pending work units.
type WorkUnitTracker struct {
	mu    sync.Mutex
	units map[string]WorkUnitInfo
}

// NewWorkUnitTracker creates a new tracker.
func NewWorkUnitTracker() *WorkUnitTracker {
	return &WorkUnitTracker{
		units: make(map[string]WorkUnitInfo),
	}
}

// Register adds a work unit to tracking.
func (t *WorkUnitTracker) Register(id string, info WorkUnitInfo) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.units[id] = info
}

// Get retrieves a work unit info.
func (t *WorkUnitTracker) Get(id string) (WorkUnitInfo, bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	info, ok := t.units[id]
	return info, ok
}

// Remove removes a work unit from tracking.
func (t *WorkUnitTracker) Remove(id string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	delete(t.units, id)
}

// Count returns the number of pending work units.
func (t *WorkUnitTracker) Count() int {
	t.mu.Lock()
	defer t.mu.Unlock()
	return len(t.units)
}

// NewJobFromState creates a job from loaded state.
func NewJobFromState(state *AudioState) *Job {
	// Initialize chapter progress map
	if state.ChapterProgress == nil {
		state.ChapterProgress = make(map[int]*ChapterProgress)
	}

	// Parse paragraphs and initialize progress for each chapter
	for _, ch := range state.Chapters {
		ch.Paragraphs = splitIntoParagraphs(ch.PolishedText)

		if _, exists := state.ChapterProgress[ch.ChapterIdx]; !exists {
			state.ChapterProgress[ch.ChapterIdx] = &ChapterProgress{
				ChapterIdx:    ch.ChapterIdx,
				TotalSegments: len(ch.Paragraphs),
				Segments:      make(map[int]*SegmentResult),
			}
		}
		state.TotalSegments += len(ch.Paragraphs)
	}

	return &Job{
		State:   state,
		Tracker: NewWorkUnitTracker(),
	}
}

// splitIntoParagraphs splits text into paragraphs.
// Paragraphs are separated by double newlines or significant whitespace.
func splitIntoParagraphs(text string) []string {
	// Normalize line endings
	text = strings.ReplaceAll(text, "\r\n", "\n")
	text = strings.ReplaceAll(text, "\r", "\n")

	// Split on double newlines (paragraph breaks)
	rawParagraphs := strings.Split(text, "\n\n")

	var paragraphs []string
	for _, p := range rawParagraphs {
		// Trim whitespace and normalize internal whitespace
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}

		// Replace single newlines with spaces (within a paragraph)
		p = strings.ReplaceAll(p, "\n", " ")

		// Collapse multiple spaces
		for strings.Contains(p, "  ") {
			p = strings.ReplaceAll(p, "  ", " ")
		}

		paragraphs = append(paragraphs, p)
	}

	return paragraphs
}

// MarkSegmentComplete marks a segment as complete in the state.
func (s *AudioState) MarkSegmentComplete(chapterIdx, paragraphIdx int, result *SegmentResult) {
	s.mu.Lock()
	defer s.mu.Unlock()

	progress, ok := s.ChapterProgress[chapterIdx]
	if !ok {
		progress = &ChapterProgress{
			ChapterIdx: chapterIdx,
			Segments:   make(map[int]*SegmentResult),
		}
		s.ChapterProgress[chapterIdx] = progress
	}

	// Only count if not already complete
	if _, exists := progress.Segments[paragraphIdx]; !exists {
		progress.CompletedSegments++
		s.CompletedSegments++
	}

	progress.Segments[paragraphIdx] = result
	progress.TotalDurationMS += result.DurationMS
	progress.TotalCostUSD += result.CostUSD
	s.TotalCostUSD += result.CostUSD
	s.TotalDurationMS += result.DurationMS
}

// IsSegmentComplete checks if a segment is already generated.
func (s *AudioState) IsSegmentComplete(chapterIdx, paragraphIdx int) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	progress, ok := s.ChapterProgress[chapterIdx]
	if !ok {
		return false
	}
	_, exists := progress.Segments[paragraphIdx]
	return exists
}

// IsChapterComplete checks if all segments for a chapter are generated.
func (s *AudioState) IsChapterComplete(chapterIdx int) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	progress, ok := s.ChapterProgress[chapterIdx]
	if !ok {
		return false
	}
	return progress.CompletedSegments >= progress.TotalSegments
}

// GetChapterSegments returns segments for a chapter in order.
func (s *AudioState) GetChapterSegments(chapterIdx int) []*SegmentResult {
	s.mu.Lock()
	defer s.mu.Unlock()

	progress, ok := s.ChapterProgress[chapterIdx]
	if !ok {
		return nil
	}

	// Get the chapter to know total paragraphs
	var totalParagraphs int
	for _, ch := range s.Chapters {
		if ch.ChapterIdx == chapterIdx {
			totalParagraphs = len(ch.Paragraphs)
			break
		}
	}

	segments := make([]*SegmentResult, 0, totalParagraphs)
	for i := 0; i < totalParagraphs; i++ {
		if seg, ok := progress.Segments[i]; ok {
			segments = append(segments, seg)
		}
	}
	return segments
}

// Job interface implementations

func (j *Job) ID() string {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.recordID
}

func (j *Job) SetRecordID(id string) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.recordID = id
}

func (j *Job) Type() string {
	return JobType
}

func (j *Job) Done() bool {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.isDone
}

func (j *Job) BookID() string {
	return j.State.BookID
}

func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return &jobs.WorkUnitMetrics{
		BookID: j.State.BookID,
		Stage:  JobType,
	}
}

func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.mu.Lock()
	defer j.mu.Unlock()

	return map[string]jobs.ProviderProgress{
		j.State.TTSProvider: {
			TotalExpected: j.State.TotalSegments,
			Completed:     j.State.CompletedSegments,
		},
	}
}
