package jobs

import (
	"sync"
	"testing"
	"time"
)

func TestPriorityQueue_BasicOrdering(t *testing.T) {
	pq := NewPriorityQueue()

	// Push units with different priorities (low first)
	pq.Push(&WorkUnit{ID: "low", Priority: PriorityLow})
	pq.Push(&WorkUnit{ID: "normal", Priority: PriorityNormal})
	pq.Push(&WorkUnit{ID: "high", Priority: PriorityHigh})

	// Pop should return in priority order (high first)
	done := make(chan struct{})
	defer close(done)

	unit := pq.TryPop()
	if unit.ID != "high" {
		t.Errorf("expected 'high', got '%s'", unit.ID)
	}

	unit = pq.TryPop()
	if unit.ID != "normal" {
		t.Errorf("expected 'normal', got '%s'", unit.ID)
	}

	unit = pq.TryPop()
	if unit.ID != "low" {
		t.Errorf("expected 'low', got '%s'", unit.ID)
	}

	// Queue should be empty
	if pq.Len() != 0 {
		t.Errorf("expected empty queue, got %d items", pq.Len())
	}
}

func TestPriorityQueue_FIFOWithinPriority(t *testing.T) {
	pq := NewPriorityQueue()

	// Push multiple units with same priority
	pq.Push(&WorkUnit{ID: "first", Priority: PriorityNormal})
	pq.Push(&WorkUnit{ID: "second", Priority: PriorityNormal})
	pq.Push(&WorkUnit{ID: "third", Priority: PriorityNormal})

	// Pop should return in FIFO order within same priority
	unit := pq.TryPop()
	if unit.ID != "first" {
		t.Errorf("expected 'first', got '%s'", unit.ID)
	}

	unit = pq.TryPop()
	if unit.ID != "second" {
		t.Errorf("expected 'second', got '%s'", unit.ID)
	}

	unit = pq.TryPop()
	if unit.ID != "third" {
		t.Errorf("expected 'third', got '%s'", unit.ID)
	}
}

func TestPriorityQueue_HighPriorityJumpsQueue(t *testing.T) {
	pq := NewPriorityQueue()

	// Simulate the issue from #161: many normal priority items queued
	for i := 0; i < 100; i++ {
		pq.Push(&WorkUnit{ID: "page_" + string(rune('0'+i%10)), Priority: PriorityNormal})
	}

	// Then a high priority item arrives
	pq.Push(&WorkUnit{ID: "toc_finder", Priority: PriorityHigh})

	// High priority should come out first despite being added last
	unit := pq.TryPop()
	if unit.ID != "toc_finder" {
		t.Errorf("expected 'toc_finder' (high priority), got '%s' with priority %d", unit.ID, unit.Priority)
	}
}

func TestPriorityQueue_Stats(t *testing.T) {
	pq := NewPriorityQueue()

	pq.Push(&WorkUnit{ID: "1", Priority: PriorityLow})
	pq.Push(&WorkUnit{ID: "2", Priority: PriorityLow})
	pq.Push(&WorkUnit{ID: "3", Priority: PriorityNormal})
	pq.Push(&WorkUnit{ID: "4", Priority: PriorityNormal})
	pq.Push(&WorkUnit{ID: "5", Priority: PriorityNormal})
	pq.Push(&WorkUnit{ID: "6", Priority: PriorityHigh})

	stats := pq.Stats()
	if stats.Total != 6 {
		t.Errorf("expected total 6, got %d", stats.Total)
	}
	if stats.High != 1 {
		t.Errorf("expected high 1, got %d", stats.High)
	}
	if stats.Normal != 3 {
		t.Errorf("expected normal 3, got %d", stats.Normal)
	}
	if stats.Low != 2 {
		t.Errorf("expected low 2, got %d", stats.Low)
	}
}

func TestPriorityQueue_BlockingPop(t *testing.T) {
	pq := NewPriorityQueue()
	done := make(chan struct{})

	// Pop on empty queue should block until item is pushed
	var result *WorkUnit
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		result = pq.Pop(done)
	}()

	// Give the goroutine time to start waiting
	time.Sleep(10 * time.Millisecond)

	// Push an item
	pq.Push(&WorkUnit{ID: "test", Priority: PriorityNormal})

	// Wait for pop to complete
	wg.Wait()

	if result == nil {
		t.Error("expected non-nil result")
	} else if result.ID != "test" {
		t.Errorf("expected 'test', got '%s'", result.ID)
	}
}

func TestPriorityQueue_PopCancellation(t *testing.T) {
	pq := NewPriorityQueue()
	done := make(chan struct{})

	var result *WorkUnit
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		result = pq.Pop(done)
	}()

	// Give the goroutine time to start waiting
	time.Sleep(10 * time.Millisecond)

	// Close done channel to cancel
	close(done)

	// Wait for pop to return
	wg.Wait()

	if result != nil {
		t.Errorf("expected nil result on cancellation, got %+v", result)
	}
}

func TestPriorityForStage(t *testing.T) {
	tests := []struct {
		stage    string
		expected int
	}{
		// Book-level operations - high priority
		{"metadata", PriorityHigh},
		{"toc_finder", PriorityHigh},
		{"toc_extract", PriorityHigh},
		{"link_toc", PriorityHigh},
		{"pattern_analysis", PriorityHigh},
		{"classify_matter", PriorityHigh},

		// Dynamic book-level keys - high priority
		{"link_entry_abc123", PriorityHigh},
		{"entry_abc123", PriorityHigh},
		{"discover_chapter1", PriorityHigh},
		{"gap_10_20", PriorityHigh},
		{"polish_chapter5", PriorityHigh},

		// Page-level operations - normal priority
		{"ocr", PriorityNormal},
		{"blend", PriorityNormal},
		{"label", PriorityNormal},
		{"extract", PriorityNormal},

		// Dynamic page-level keys - normal priority
		{"page_0001_blend", PriorityNormal},
		{"page_0042_label", PriorityNormal},
		{"page_0100_openrouter", PriorityNormal},

		// Unknown defaults to normal
		{"unknown", PriorityNormal},
		{"", PriorityNormal},
	}

	for _, tt := range tests {
		t.Run(tt.stage, func(t *testing.T) {
			got := PriorityForStage(tt.stage)
			if got != tt.expected {
				t.Errorf("PriorityForStage(%q) = %d, want %d", tt.stage, got, tt.expected)
			}
		})
	}
}

func TestPriorityQueue_ConcurrentAccess(t *testing.T) {
	pq := NewPriorityQueue()

	const numProducers = 5
	const itemsPerProducer = 100

	var wg sync.WaitGroup

	// Producers push items concurrently
	for i := 0; i < numProducers; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			for j := 0; j < itemsPerProducer; j++ {
				priority := PriorityNormal
				if j%10 == 0 {
					priority = PriorityHigh
				}
				pq.Push(&WorkUnit{
					ID:       "test",
					Priority: priority,
				})
			}
		}(i)
	}

	// Wait for all producers to finish
	wg.Wait()

	// Verify we can pop all items
	expectedTotal := numProducers * itemsPerProducer
	if pq.Len() != expectedTotal {
		t.Errorf("expected queue length %d, got %d", expectedTotal, pq.Len())
	}

	// Pop all items and count by priority
	highCount := 0
	normalCount := 0
	for i := 0; i < expectedTotal; i++ {
		unit := pq.TryPop()
		if unit == nil {
			t.Errorf("expected item at position %d, got nil", i)
			break
		}
		if unit.Priority == PriorityHigh {
			highCount++
		} else {
			normalCount++
		}
	}

	expectedHigh := numProducers * (itemsPerProducer / 10)
	expectedNormal := expectedTotal - expectedHigh

	if highCount != expectedHigh {
		t.Errorf("expected %d high priority items, got %d", expectedHigh, highCount)
	}
	if normalCount != expectedNormal {
		t.Errorf("expected %d normal priority items, got %d", expectedNormal, normalCount)
	}

	// Queue should be empty now
	if pq.Len() != 0 {
		t.Errorf("expected empty queue, got %d items", pq.Len())
	}
}
