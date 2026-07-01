package common

import (
	"fmt"
)

// --- Structure State Types ---

// ChapterState tracks chapter during structure processing.
type ChapterState struct {
	// Identity
	EntryID   string `json:"entry_id"`   // Unique within book (e.g., "ch_001")
	UniqueKey string `json:"unique_key"` // For upsert: "{book_id}:{toc_entry_id}" or "{book_id}:orphan:{sort_order}"
	DocID     string `json:"doc_id"`     // DefraDB doc ID (after create)
	CID       string `json:"cid"`        // DefraDB commit CID (latest)

	// From ToC
	Title       string `json:"title"`
	Level       int    `json:"level"`
	LevelName   string `json:"level_name"`
	EntryNumber string `json:"entry_number"`
	SortOrder   int    `json:"sort_order"`
	Source      string `json:"source"`       // "toc", "heading", "reconciled"
	TocEntryID  string `json:"toc_entry_id"` // Link back to original TocEntry

	// Page boundaries
	StartPage int `json:"start_page"`
	EndPage   int `json:"end_page"`

	// Hierarchy
	ParentID string `json:"parent_id"` // entry_id of parent chapter

	// Matter classification (set in classify phase)
	MatterType        string `json:"matter_type"`        // "front_matter", "body", "back_matter"
	ClassifyReasoning string `json:"classify_reasoning"` // Why this classification was chosen

	// Content classification (granular, set in classify phase)
	ContentType           string `json:"content_type"`            // "preface", "body", "appendix", etc.
	AudioInclude          bool   `json:"audio_include"`           // Include in audiobook output
	AudioIncludeReasoning string `json:"audio_include_reasoning"` // Why include/exclude

	// Text content (set in extract phase)
	MechanicalText string `json:"mechanical_text,omitempty"`
	PageBreaks     []int  `json:"page_breaks,omitempty"`

	// Polished text (set in polish phase)
	PolishedText     string `json:"polished_text,omitempty"`
	WordCount        int    `json:"word_count"`
	EditsAppliedJSON string `json:"edits_applied_json,omitempty"`

	// Processing state
	ExtractDone  bool `json:"extract_done"`
	PolishDone   bool `json:"polish_done"`
	PolishFailed bool `json:"polish_failed"` // True if polish failed and fell back to mechanical text
}

// Copy returns a deep copy of the ChapterState.
func (c *ChapterState) Copy() *ChapterState {
	if c == nil {
		return nil
	}
	copy := *c // Shallow copy of all value fields
	// Deep copy the slice
	if c.PageBreaks != nil {
		copy.PageBreaks = make([]int, len(c.PageBreaks))
		for i, v := range c.PageBreaks {
			copy.PageBreaks[i] = v
		}
	}
	return &copy
}

// NewChapterState creates a new ChapterState with validation.
// Returns an error if required fields are missing or invalid.
func NewChapterState(entryID, uniqueKey, title string, startPage int) (*ChapterState, error) {
	if entryID == "" {
		return nil, fmt.Errorf("entry_id is required")
	}
	if uniqueKey == "" {
		return nil, fmt.Errorf("unique_key is required")
	}
	if title == "" {
		return nil, fmt.Errorf("title is required")
	}
	if startPage < 1 {
		return nil, fmt.Errorf("start_page must be >= 1, got %d", startPage)
	}
	return &ChapterState{
		EntryID:   entryID,
		UniqueKey: uniqueKey,
		Title:     title,
		StartPage: startPage,
	}, nil
}

// StructureState holds structure sub-job state within BookState (for serialization).
type StructureState struct {
	Phase              string            `json:"phase"` // build, extract, classify, polish, finalize
	Chapters           []*ChapterState   `json:"chapters"`
	ChaptersToExtract  int               `json:"chapters_to_extract"`
	ChaptersExtracted  int               `json:"chapters_extracted"`
	ExtractsFailed     int               `json:"extracts_failed"`
	ClassifyPending    bool              `json:"classify_pending"`
	Classifications    map[string]string `json:"classifications"`     // entry_id -> matter_type
	ClassifyReasonings map[string]string `json:"classify_reasonings"` // entry_id -> reasoning
	ChaptersToPolish   int               `json:"chapters_to_polish"`
	ChaptersPolished   int               `json:"chapters_polished"`
	PolishFailed       int               `json:"polish_failed"`
}

// GetStructureChapters returns deep copies of all structure chapters.
// Modifications to returned chapters do not affect BookState.
// Use UpdateChapter() to save changes back.
func (b *BookState) GetStructureChapters() []*ChapterState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.structureChapters == nil {
		return nil
	}
	result := make([]*ChapterState, len(b.structureChapters))
	for i, ch := range b.structureChapters {
		result[i] = ch.Copy()
	}
	return result
}

// SetStructureChapters sets the structure chapters (thread-safe).
func (b *BookState) SetStructureChapters(chapters []*ChapterState) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureChapters = chapters
	for _, chapter := range chapters {
		if chapter == nil {
			continue
		}
		b.trackCIDLocked("Chapter", chapter.DocID, chapter.CID)
	}
}

// GetStructureClassifications returns the matter classifications (thread-safe).
// Returns a copy of the map to prevent external modification.
func (b *BookState) GetStructureClassifications() map[string]string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.structureClassifications == nil {
		return nil
	}
	result := make(map[string]string, len(b.structureClassifications))
	for k, v := range b.structureClassifications {
		result[k] = v
	}
	return result
}

// SetStructureClassifications sets the matter classifications (thread-safe).
func (b *BookState) SetStructureClassifications(classifications map[string]string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureClassifications = classifications
}

// GetStructureClassifyPending returns whether classification is pending (thread-safe).
func (b *BookState) GetStructureClassifyPending() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structureClassifyPending
}

// SetStructureClassifyPending sets whether classification is pending (thread-safe).
func (b *BookState) SetStructureClassifyPending(pending bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureClassifyPending = pending
}

// GetChapterByEntryID returns a copy of the chapter by its entry ID.
// Returns nil if not found. Callers should modify the copy and then call
// UpdateChapter() to save changes back to BookState.
func (b *BookState) GetChapterByEntryID(entryID string) *ChapterState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	for _, ch := range b.structureChapters {
		if ch.EntryID == entryID {
			return ch.Copy()
		}
	}
	return nil
}

// UpdateChapter updates a chapter in the list (thread-safe).
func (b *BookState) UpdateChapter(chapter *ChapterState) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for i, ch := range b.structureChapters {
		if ch.EntryID == chapter.EntryID {
			b.structureChapters[i] = chapter
			return
		}
	}
}

// --- Structure Classification Reasonings ---

// GetStructureClassifyReasonings returns the classification reasonings map (thread-safe).
// Returns a copy of the map to prevent external modification.
func (b *BookState) GetStructureClassifyReasonings() map[string]string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.structureClassifyReasonings == nil {
		return nil
	}
	result := make(map[string]string, len(b.structureClassifyReasonings))
	for k, v := range b.structureClassifyReasonings {
		result[k] = v
	}
	return result
}

// SetStructureClassifyReasonings sets the classification reasonings map (thread-safe).
func (b *BookState) SetStructureClassifyReasonings(reasonings map[string]string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureClassifyReasonings = reasonings
}
