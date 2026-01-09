package jobs

import (
	"container/heap"
	"sync"
)

// Priority levels for work units.
// Higher values are processed first.
const (
	PriorityLow    = 0  // Background/optional operations
	PriorityNormal = 10 // Page-level operations (blend, label, ocr, extract)
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
	case "ocr", "blend", "label", "extract":
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
	mu    sync.Mutex
	cond  *sync.Cond
	items workUnitHeap
	seq   uint64 // Sequence number for FIFO ordering within same priority
}

// NewPriorityQueue creates a new priority queue.
func NewPriorityQueue() *PriorityQueue {
	pq := &PriorityQueue{
		items: make(workUnitHeap, 0),
	}
	pq.cond = sync.NewCond(&pq.mu)
	heap.Init(&pq.items)
	return pq
}

// Push adds a work unit to the queue.
func (pq *PriorityQueue) Push(unit *WorkUnit) {
	pq.mu.Lock()
	defer pq.mu.Unlock()

	pq.seq++
	item := &workUnitItem{
		unit: unit,
		seq:  pq.seq,
	}
	heap.Push(&pq.items, item)
	pq.cond.Signal() // Wake up one waiting consumer
}

// Pop removes and returns the highest priority work unit.
// Blocks until an item is available or the done channel is closed.
// Returns nil if done is closed while waiting.
func (pq *PriorityQueue) Pop(done <-chan struct{}) *WorkUnit {
	pq.mu.Lock()
	defer pq.mu.Unlock()

	for pq.items.Len() == 0 {
		// Check if done before waiting
		select {
		case <-done:
			return nil
		default:
		}

		// Wait for signal or done
		// Use a goroutine to handle done channel since cond.Wait doesn't support select
		waiting := make(chan struct{})
		go func() {
			select {
			case <-done:
				pq.cond.Broadcast() // Wake up all waiters
			case <-waiting:
			}
		}()

		pq.cond.Wait()
		close(waiting)

		// Check done again after waking
		select {
		case <-done:
			return nil
		default:
		}
	}

	item := heap.Pop(&pq.items).(*workUnitItem)
	return item.unit
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
