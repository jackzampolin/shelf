package jobs

import (
	"container/heap"
	"errors"
	"sync"
)

// ErrNilWorkUnit is returned when attempting to push a nil work unit.
var ErrNilWorkUnit = errors.New("cannot push nil work unit")

// Priority levels for work units.
// Higher values are processed first.
const (
	PriorityLow    = 0  // Background/optional operations
	PriorityNormal = 10 // Page-level operations (ocr, extract)
	PriorityHigh   = 20 // Book-level operations (toc_finder, toc_extract, link_toc, metadata, finalize, structure)
)

// PriorityForStage returns the appropriate priority for a given stage or item key.
// Book-level operations get PriorityHigh, page-level operations get PriorityNormal.
// This function handles both exact matches and prefix-based patterns.
func PriorityForStage(stageOrKey string) int {
	// Check exact matches first (most common)
	switch stageOrKey {
	// Book-level operations - high priority
	case "metadata", "toc_finder", "toc_extract", "link_toc",
		"finalize_toc", "finalize_pattern", "finalize_discover", "finalize_gap",
		"structure", "structure_classify", "structure_polish",
		"pattern_analysis", "classify_matter":
		return PriorityHigh

	// Page-level operations - normal priority
	case "ocr", "extract":
		return PriorityNormal
	}

	// Check prefix patterns for dynamic keys
	if len(stageOrKey) >= 4 {
		switch {
		// Book-level prefixes - high priority
		case hasPrefix(stageOrKey, "link_entry_"),
			hasPrefix(stageOrKey, "entry_"),
			hasPrefix(stageOrKey, "discover_"),
			hasPrefix(stageOrKey, "gap_"),
			hasPrefix(stageOrKey, "polish_"):
			return PriorityHigh

		// Page-level prefixes - normal priority
		case hasPrefix(stageOrKey, "page_"):
			return PriorityNormal
		}
	}

	// Default to normal
	return PriorityNormal
}

// hasPrefix is a simple helper to avoid importing strings package.
func hasPrefix(s, prefix string) bool {
	return len(s) >= len(prefix) && s[:len(prefix)] == prefix
}

// PriorityQueue is a thread-safe priority queue for work units.
// Work units with higher Priority values are dequeued first.
// When priorities are equal, work units are processed in FIFO order.
type PriorityQueue struct {
	mu     sync.Mutex
	items  workUnitHeap
	seq    uint64          // Sequence number for FIFO ordering within same priority
	notify chan struct{}   // Signaled when items are pushed
}

// NewPriorityQueue creates a new priority queue.
func NewPriorityQueue() *PriorityQueue {
	pq := &PriorityQueue{
		items:  make(workUnitHeap, 0),
		notify: make(chan struct{}, 1), // Buffered to avoid blocking Push
	}
	heap.Init(&pq.items)
	return pq
}

// Push adds a work unit to the queue.
// Returns an error if unit is nil.
func (pq *PriorityQueue) Push(unit *WorkUnit) error {
	if unit == nil {
		return ErrNilWorkUnit
	}

	pq.mu.Lock()
	pq.seq++
	item := &workUnitItem{
		unit: unit,
		seq:  pq.seq,
	}
	heap.Push(&pq.items, item)
	pq.mu.Unlock()

	// Signal waiting consumers (non-blocking)
	select {
	case pq.notify <- struct{}{}:
	default:
		// Channel already has a pending notification
	}
	return nil
}

// Pop removes and returns the highest priority work unit.
// Blocks until an item is available or the done channel is closed.
// Returns nil if done is closed while waiting.
func (pq *PriorityQueue) Pop(done <-chan struct{}) *WorkUnit {
	for {
		// Try to get an item
		pq.mu.Lock()
		if pq.items.Len() > 0 {
			item := heap.Pop(&pq.items).(*workUnitItem)
			pq.mu.Unlock()
			return item.unit
		}
		pq.mu.Unlock()

		// Wait for notification or cancellation
		select {
		case <-done:
			return nil
		case <-pq.notify:
			// Item may have been pushed, loop to check
		}
	}
}

// TryPop attempts to pop without blocking.
// Returns nil if queue is empty.
func (pq *PriorityQueue) TryPop() *WorkUnit {
	pq.mu.Lock()
	defer pq.mu.Unlock()

	if pq.items.Len() == 0 {
		return nil
	}

	item := heap.Pop(&pq.items).(*workUnitItem)
	return item.unit
}

// Len returns the number of items in the queue.
func (pq *PriorityQueue) Len() int {
	pq.mu.Lock()
	defer pq.mu.Unlock()
	return pq.items.Len()
}

// Stats returns queue statistics by priority level.
func (pq *PriorityQueue) Stats() PriorityQueueStats {
	pq.mu.Lock()
	defer pq.mu.Unlock()

	stats := PriorityQueueStats{
		Total: pq.items.Len(),
	}

	for _, item := range pq.items {
		switch {
		case item.unit.Priority >= PriorityHigh:
			stats.High++
		case item.unit.Priority >= PriorityNormal:
			stats.Normal++
		default:
			stats.Low++
		}
	}

	return stats
}

// PriorityQueueStats reports queue depth by priority level.
type PriorityQueueStats struct {
	Total  int `json:"total"`
	High   int `json:"high"`
	Normal int `json:"normal"`
	Low    int `json:"low"`
}

// workUnitItem wraps a WorkUnit with sequence number for heap ordering.
type workUnitItem struct {
	unit *WorkUnit
	seq  uint64 // For FIFO ordering within same priority
}

// workUnitHeap implements heap.Interface for work units.
// Higher priority items come first. Equal priorities use FIFO (lower seq first).
type workUnitHeap []*workUnitItem

func (h workUnitHeap) Len() int { return len(h) }

func (h workUnitHeap) Less(i, j int) bool {
	// Higher priority comes first (max-heap behavior)
	if h[i].unit.Priority != h[j].unit.Priority {
		return h[i].unit.Priority > h[j].unit.Priority
	}
	// Same priority: lower sequence number (earlier) comes first (FIFO)
	return h[i].seq < h[j].seq
}

func (h workUnitHeap) Swap(i, j int) {
	h[i], h[j] = h[j], h[i]
}

func (h *workUnitHeap) Push(x any) {
	*h = append(*h, x.(*workUnitItem))
}

func (h *workUnitHeap) Pop() any {
	old := *h
	n := len(old)
	item := old[n-1]
	old[n-1] = nil // Avoid memory leak
	*h = old[0 : n-1]
	return item
}
