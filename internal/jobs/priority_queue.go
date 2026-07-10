package jobs

import (
	"container/heap"
	"errors"
	"fmt"
	"sort"
	"sync"
)

// ErrNilWorkUnit is returned when attempting to push a nil work unit.
var ErrNilWorkUnit = errors.New("cannot push nil work unit")

// Priority levels for work units. Higher values are processed first within a
// job; jobs themselves are scheduled round-robin so one large book cannot
// starve repairs or smaller books.
const (
	PriorityLow    = 0
	PriorityNormal = 10
	PriorityHigh   = 20
)

// PriorityForStage returns the appropriate priority for a given stage or item key.
func PriorityForStage(stageOrKey string) int {
	switch stageOrKey {
	case "metadata", "toc_finder", "toc_extract", "link_toc",
		"finalize_toc", "finalize_pattern", "finalize_discover", "finalize_gap",
		"structure", "structure_classify", "structure_polish",
		"pattern_analysis", "classify_matter":
		return PriorityHigh
	case "ocr", "extract":
		return PriorityNormal
	}

	if len(stageOrKey) >= 4 {
		switch {
		case hasPrefix(stageOrKey, "link_entry_"),
			hasPrefix(stageOrKey, "entry_"),
			hasPrefix(stageOrKey, "discover_"),
			hasPrefix(stageOrKey, "gap_"),
			hasPrefix(stageOrKey, "polish_"):
			return PriorityHigh
		case hasPrefix(stageOrKey, "page_"):
			return PriorityNormal
		}
	}
	return PriorityNormal
}

func hasPrefix(s, prefix string) bool {
	return len(s) >= len(prefix) && s[:len(prefix)] == prefix
}

// PriorityQueue is a fair, thread-safe queue. Each active job receives one
// dispatch turn per round. Within that job, high-priority book operations jump
// ahead of its page work and equal priorities retain FIFO order.
type PriorityQueue struct {
	mu sync.Mutex

	books   map[string]*bookWorkQueue
	order   []string
	cursor  int
	total   int
	seq     uint64
	started bool

	notify chan struct{}
}

type bookWorkQueue struct {
	key      string
	bookSeq  int64
	firstSeq uint64
	items    workUnitHeap
}

func NewPriorityQueue() *PriorityQueue {
	return &PriorityQueue{
		books:  make(map[string]*bookWorkQueue),
		notify: make(chan struct{}, 1),
	}
}

func queueKey(unit *WorkUnit) string {
	if unit.JobID != "" {
		return "job:" + unit.JobID
	}
	if unit.BookSeq != 0 {
		return fmt.Sprintf("book:%d", unit.BookSeq)
	}
	// Tests and legacy callers without job identity share a conventional queue,
	// preserving ordinary priority/FIFO semantics.
	return "unset"
}

func (pq *PriorityQueue) Push(unit *WorkUnit) error {
	if unit == nil {
		return ErrNilWorkUnit
	}

	pq.mu.Lock()
	pq.seq++
	key := queueKey(unit)
	bq := pq.books[key]
	if bq == nil {
		bq = &bookWorkQueue{key: key, bookSeq: unit.BookSeq, firstSeq: pq.seq}
		heap.Init(&bq.items)
		pq.books[key] = bq
		pq.order = append(pq.order, key)
		// Before dispatch begins, retain deterministic created-at ordering. Once
		// running, new jobs join the end of the current fair round.
		if !pq.started {
			sort.SliceStable(pq.order, func(i, j int) bool {
				return bookQueueBefore(pq.books[pq.order[i]], pq.books[pq.order[j]])
			})
		}
	}
	heap.Push(&bq.items, &workUnitItem{unit: unit, seq: pq.seq})
	pq.total++
	pq.mu.Unlock()

	pq.signal()
	return nil
}

func bookQueueBefore(left, right *bookWorkQueue) bool {
	if left.bookSeq != right.bookSeq {
		if left.bookSeq == 0 {
			return false
		}
		if right.bookSeq == 0 {
			return true
		}
		return left.bookSeq < right.bookSeq
	}
	return left.firstSeq < right.firstSeq
}

func (pq *PriorityQueue) signal() {
	select {
	case pq.notify <- struct{}{}:
	default:
	}
}

func (pq *PriorityQueue) Pop(done <-chan struct{}) *WorkUnit {
	for {
		if unit := pq.TryPop(); unit != nil {
			return unit
		}
		select {
		case <-done:
			return nil
		case <-pq.notify:
		}
	}
}

func (pq *PriorityQueue) TryPop() *WorkUnit {
	pq.mu.Lock()
	if pq.total == 0 {
		pq.mu.Unlock()
		return nil
	}
	pq.started = true
	if pq.cursor >= len(pq.order) {
		pq.cursor = 0
	}

	key := pq.order[pq.cursor]
	bq := pq.books[key]
	item := heap.Pop(&bq.items).(*workUnitItem)
	pq.total--
	if bq.items.Len() == 0 {
		delete(pq.books, key)
		pq.order = append(pq.order[:pq.cursor], pq.order[pq.cursor+1:]...)
		if pq.cursor >= len(pq.order) {
			pq.cursor = 0
		}
	} else {
		pq.cursor = (pq.cursor + 1) % len(pq.order)
	}
	hasMore := pq.total > 0
	pq.mu.Unlock()
	if hasMore {
		pq.signal()
	}
	return item.unit
}

func (pq *PriorityQueue) Len() int {
	pq.mu.Lock()
	defer pq.mu.Unlock()
	return pq.total
}

func (pq *PriorityQueue) JobIDs() []string {
	pq.mu.Lock()
	defer pq.mu.Unlock()
	seen := make(map[string]struct{})
	for _, bq := range pq.books {
		for _, item := range bq.items {
			if item.unit.JobID != "" {
				seen[item.unit.JobID] = struct{}{}
			}
		}
	}
	ids := make([]string, 0, len(seen))
	for id := range seen {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func (pq *PriorityQueue) RemoveJob(jobID string) int {
	if jobID == "" {
		return 0
	}
	pq.mu.Lock()
	defer pq.mu.Unlock()

	removed := 0
	newOrder := make([]string, 0, len(pq.order))
	for _, key := range pq.order {
		bq := pq.books[key]
		kept := bq.items[:0]
		for _, item := range bq.items {
			if item.unit.JobID == jobID {
				removed++
				continue
			}
			kept = append(kept, item)
		}
		bq.items = kept
		if bq.items.Len() == 0 {
			delete(pq.books, key)
			continue
		}
		heap.Init(&bq.items)
		newOrder = append(newOrder, key)
	}
	pq.order = newOrder
	pq.total -= removed
	if pq.cursor >= len(pq.order) {
		pq.cursor = 0
	}
	return removed
}

func (pq *PriorityQueue) Stats() PriorityQueueStats {
	pq.mu.Lock()
	defer pq.mu.Unlock()
	stats := PriorityQueueStats{Total: pq.total}
	for _, bq := range pq.books {
		for _, item := range bq.items {
			switch {
			case item.unit.Priority >= PriorityHigh:
				stats.High++
			case item.unit.Priority >= PriorityNormal:
				stats.Normal++
			default:
				stats.Low++
			}
		}
	}
	return stats
}

type PriorityQueueStats struct {
	Total  int `json:"total"`
	High   int `json:"high"`
	Normal int `json:"normal"`
	Low    int `json:"low"`
}

type workUnitItem struct {
	unit *WorkUnit
	seq  uint64
}

type workUnitHeap []*workUnitItem

func (h workUnitHeap) Len() int { return len(h) }

func (h workUnitHeap) Less(i, j int) bool {
	if h[i].unit.Priority != h[j].unit.Priority {
		return h[i].unit.Priority > h[j].unit.Priority
	}
	return h[i].seq < h[j].seq
}

func (h workUnitHeap) Swap(i, j int) { h[i], h[j] = h[j], h[i] }

func (h *workUnitHeap) Push(x any) { *h = append(*h, x.(*workUnitItem)) }

func (h *workUnitHeap) Pop() any {
	old := *h
	n := len(old)
	item := old[n-1]
	old[n-1] = nil
	*h = old[:n-1]
	return item
}
