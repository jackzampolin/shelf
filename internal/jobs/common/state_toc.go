package common

import (
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
)

// --- Thread-safe accessors for mutable ToC fields ---

// GetTocFound returns whether a ToC was found (thread-safe).
func (b *BookState) GetTocFound() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocFound
}

// SetTocFound sets whether a ToC was found (thread-safe).
func (b *BookState) SetTocFound(found bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocFound = found
}

// GetTocPageRange returns the ToC page range (thread-safe).
// Returns (startPage, endPage).
func (b *BookState) GetTocPageRange() (int, int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocStartPage, b.tocEndPage
}

// SetTocPageRange sets the ToC page range (thread-safe).
func (b *BookState) SetTocPageRange(startPage, endPage int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocStartPage = startPage
	b.tocEndPage = endPage
}

// SetTocResult sets all ToC finder results atomically (thread-safe).
func (b *BookState) SetTocResult(found bool, startPage, endPage int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocFound = found
	b.tocStartPage = startPage
	b.tocEndPage = endPage
}

// --- Thread-safe accessors for Prompts ---

// GetPrompt returns the resolved prompt text for a key (thread-safe).
func (b *BookState) GetPrompt(key string) string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.Prompts[key]
}

// GetPromptCID returns the prompt CID for a key (thread-safe).
func (b *BookState) GetPromptCID(key string) string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.PromptCIDs[key]
}

// --- Thread-safe accessors for TocEntries ---

// GetTocEntries returns the ToC entries (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetTocEntries() []*toc_entry_finder.TocEntry {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.tocEntries == nil {
		return nil
	}
	result := make([]*toc_entry_finder.TocEntry, len(b.tocEntries))
	copy(result, b.tocEntries)
	return result
}

// SetTocEntries sets the ToC entries (thread-safe).
func (b *BookState) SetTocEntries(entries []*toc_entry_finder.TocEntry) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocEntries = entries
}

// GetUnlinkedTocEntries returns only entries without actual_page linked.
// This filters the cached entries rather than re-querying DB.
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetUnlinkedTocEntries() []*toc_entry_finder.TocEntry {
	b.mu.RLock()
	defer b.mu.RUnlock()
	// TocEntries are already filtered to unlinked during load
	if b.tocEntries == nil {
		return nil
	}
	result := make([]*toc_entry_finder.TocEntry, len(b.tocEntries))
	copy(result, b.tocEntries)
	return result
}

// --- ToC Link Progress ---

// GetTocLinkProgress returns toc link progress counters (thread-safe).
func (b *BookState) GetTocLinkProgress() (total, done int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.tocLinkEntriesTotal, b.tocLinkEntriesDone
}

// SetTocLinkProgress sets toc link progress counters (thread-safe).
func (b *BookState) SetTocLinkProgress(total, done int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocLinkEntriesTotal = total
	b.tocLinkEntriesDone = done
}

// IncrementTocLinkEntriesDone increments entries done (thread-safe).
func (b *BookState) IncrementTocLinkEntriesDone() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.tocLinkEntriesDone++
}
