package common

// --- Thread-safe accessors for LinkedEntries ---

// GetLinkedEntries returns the linked ToC entries (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetLinkedEntries() []*LinkedTocEntry {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.linkedEntries == nil {
		return nil
	}
	result := make([]*LinkedTocEntry, len(b.linkedEntries))
	copy(result, b.linkedEntries)
	return result
}

// SetLinkedEntries sets the linked ToC entries (thread-safe).
func (b *BookState) SetLinkedEntries(entries []*LinkedTocEntry) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.linkedEntries = entries
}

// HasLinkedEntries returns true if linked entries are cached (thread-safe).
func (b *BookState) HasLinkedEntries() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.linkedEntries != nil
}

// SetStructurePhase sets the current structure processing phase (thread-safe).
func (b *BookState) SetStructurePhase(phase string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structurePhase = phase
}

// GetStructurePhase gets the current structure processing phase (thread-safe).
func (b *BookState) GetStructurePhase() string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structurePhase
}

// SetStructureProgress sets the structure progress counters (thread-safe).
func (b *BookState) SetStructureProgress(total, extracted, polished, failed int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureChaptersTotal = total
	b.structureChaptersExtracted = extracted
	b.structureChaptersPolished = polished
	b.structurePolishFailed = failed
}

// GetStructureProgress gets the structure progress counters (thread-safe).
func (b *BookState) GetStructureProgress() (total, extracted, polished, failed int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.structureChaptersTotal, b.structureChaptersExtracted, b.structureChaptersPolished, b.structurePolishFailed
}

// IncrementStructurePolished increments the polished counter (thread-safe).
func (b *BookState) IncrementStructurePolished() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structureChaptersPolished++
}

// IncrementStructurePolishFailed increments the polish failed counter (thread-safe).
func (b *BookState) IncrementStructurePolishFailed() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.structurePolishFailed++
}

// --- Body Page Range Accessors ---

// GetBodyRange returns the body page range (thread-safe).
func (b *BookState) GetBodyRange() (start, end int) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.bodyStart, b.bodyEnd
}

// SetBodyRange sets the body page range (thread-safe).
func (b *BookState) SetBodyRange(start, end int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.bodyStart = start
	b.bodyEnd = end
}

// GetBodyStart returns the body start page (thread-safe).
func (b *BookState) GetBodyStart() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.bodyStart
}

// GetBodyEnd returns the body end page (thread-safe).
func (b *BookState) GetBodyEnd() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.bodyEnd
}
