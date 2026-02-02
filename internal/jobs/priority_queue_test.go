package jobs

import (
	"fmt"
	"runtime"
	"sync"
	"testing"
	"time"
)

// mustPush is a test helper that panics if Push fails
func mustPush(t *testing.T, pq *PriorityQueue, unit *WorkUnit) {
	t.Helper()
	if err := pq.Push(unit); err != nil {
		t.Fatalf("Push failed: %v", err)
	}
}

func TestPriorityQueue_BasicOrdering(t *testing.T) {
	pq := NewPriorityQueue()

	// Push units with different priorities (low first)
	mustPush(t, pq, &WorkUnit{ID: "low", Priority: PriorityLow})
	mustPush(t, pq, &WorkUnit{ID: "normal", Priority: PriorityNormal})
	mustPush(t, pq, &WorkUnit{ID: "high", Priority: PriorityHigh})

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
	mustPush(t, pq, &WorkUnit{ID: "first", Priority: PriorityNormal})
	mustPush(t, pq, &WorkUnit{ID: "second", Priority: PriorityNormal})
	mustPush(t, pq, &WorkUnit{ID: "third", Priority: PriorityNormal})

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
		mustPush(t, pq, &WorkUnit{ID: "page_" + string(rune('0'+i%10)), Priority: PriorityNormal})
	}

	// Then a high priority item arrives
	mustPush(t, pq, &WorkUnit{ID: "toc_finder", Priority: PriorityHigh})

	// High priority should come out first despite being added last
	unit := pq.TryPop()
	if unit.ID != "toc_finder" {
		t.Errorf("expected 'toc_finder' (high priority), got '%s' with priority %d", unit.ID, unit.Priority)
	}
}

func TestPriorityQueue_Stats(t *testing.T) {
	pq := NewPriorityQueue()

	mustPush(t, pq, &WorkUnit{ID: "1", Priority: PriorityLow})
	mustPush(t, pq, &WorkUnit{ID: "2", Priority: PriorityLow})
	mustPush(t, pq, &WorkUnit{ID: "3", Priority: PriorityNormal})
	mustPush(t, pq, &WorkUnit{ID: "4", Priority: PriorityNormal})
	mustPush(t, pq, &WorkUnit{ID: "5", Priority: PriorityNormal})
	mustPush(t, pq, &WorkUnit{ID: "6", Priority: PriorityHigh})

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
	mustPush(t, pq, &WorkUnit{ID: "test", Priority: PriorityNormal})

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
		{"extract", PriorityNormal},

		// Dynamic page-level keys - normal priority
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
				if err := pq.Push(&WorkUnit{
					ID:       "test",
					Priority: priority,
				}); err != nil {
					t.Errorf("Push failed: %v", err)
				}
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

func TestPriorityQueue_TryPopEmpty(t *testing.T) {
	pq := NewPriorityQueue()

	// TryPop on empty queue should return nil without blocking
	result := pq.TryPop()
	if result != nil {
		t.Errorf("expected nil from empty queue, got %+v", result)
	}

	// Queue should still be usable after TryPop on empty
	mustPush(t, pq, &WorkUnit{ID: "test", Priority: PriorityNormal})
	result = pq.TryPop()
	if result == nil || result.ID != "test" {
		t.Errorf("queue not usable after TryPop on empty, got %+v", result)
	}
}

func TestPriorityQueue_StatsEmpty(t *testing.T) {
	pq := NewPriorityQueue()

	stats := pq.Stats()
	if stats.Total != 0 {
		t.Errorf("expected Total=0 for empty queue, got %d", stats.Total)
	}
	if stats.High != 0 {
		t.Errorf("expected High=0 for empty queue, got %d", stats.High)
	}
	if stats.Normal != 0 {
		t.Errorf("expected Normal=0 for empty queue, got %d", stats.Normal)
	}
	if stats.Low != 0 {
		t.Errorf("expected Low=0 for empty queue, got %d", stats.Low)
	}
}

func TestPriorityQueue_PushNil(t *testing.T) {
	pq := NewPriorityQueue()

	// Push nil should return error
	err := pq.Push(nil)
	if err == nil {
		t.Error("expected error when pushing nil, got nil")
	}
	if err != ErrNilWorkUnit {
		t.Errorf("expected ErrNilWorkUnit, got %v", err)
	}

	// Queue should still be usable after push error
	if err := pq.Push(&WorkUnit{ID: "test", Priority: PriorityNormal}); err != nil {
		t.Errorf("Push failed after nil push: %v", err)
	}
	if pq.Len() != 1 {
		t.Errorf("expected queue length 1, got %d", pq.Len())
	}
}

func TestPriorityQueue_MultipleConcurrentConsumers(t *testing.T) {
	pq := NewPriorityQueue()
	done := make(chan struct{})

	const numConsumers = 10
	const numItems = 5

	results := make(chan *WorkUnit, numConsumers)
	var wg sync.WaitGroup

	// Start consumers before any items exist
	for i := 0; i < numConsumers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			unit := pq.Pop(done)
			results <- unit
		}()
	}

	// Give consumers time to start waiting
	time.Sleep(20 * time.Millisecond)

	// Push fewer items than consumers
	for i := 0; i < numItems; i++ {
		mustPush(t, pq, &WorkUnit{ID: fmt.Sprintf("item_%d", i), Priority: PriorityNormal})
	}

	// Give items time to be consumed
	time.Sleep(20 * time.Millisecond)

	// Close done to unblock remaining consumers
	close(done)
	wg.Wait()
	close(results)

	// Verify exactly numItems were successfully consumed
	gotItems := 0
	gotNils := 0
	for result := range results {
		if result != nil {
			gotItems++
		} else {
			gotNils++
		}
	}

	if gotItems != numItems {
		t.Errorf("expected %d items consumed, got %d", numItems, gotItems)
	}
	expectedNils := numConsumers - numItems
	if gotNils != expectedNils {
		t.Errorf("expected %d nil results (cancelled consumers), got %d", expectedNils, gotNils)
	}
}

func TestPriorityQueue_NoGoroutineLeak(t *testing.T) {
	// Get baseline goroutine count
	runtime.GC()
	time.Sleep(10 * time.Millisecond)
	initialGoroutines := runtime.NumGoroutine()

	// Run many pop/cancel cycles
	for i := 0; i < 50; i++ {
		pq := NewPriorityQueue()
		done := make(chan struct{})

		var wg sync.WaitGroup
		wg.Add(1)
		go func() {
			defer wg.Done()
			pq.Pop(done)
		}()

		time.Sleep(time.Millisecond)
		close(done)
		wg.Wait()
	}

	// Allow goroutines to clean up
	runtime.GC()
	time.Sleep(50 * time.Millisecond)

	finalGoroutines := runtime.NumGoroutine()
	// Allow some variance for runtime goroutines
	if finalGoroutines > initialGoroutines+5 {
		t.Errorf("possible goroutine leak: started with %d, ended with %d",
			initialGoroutines, finalGoroutines)
	}
}

func TestPriorityForStage_EdgeCases(t *testing.T) {
	tests := []struct {
		input    string
		expected int
	}{
		{"lin", PriorityNormal},          // Short prefix that doesn't match
		{"link_entry_", PriorityHigh},    // Exact prefix match
		{"a", PriorityNormal},            // Very short input
		{"abc", PriorityNormal},          // Below length threshold
		{"link", PriorityNormal},         // Partial prefix
		{"entry_x", PriorityHigh},        // Valid prefix
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			got := PriorityForStage(tt.input)
			if got != tt.expected {
				t.Errorf("PriorityForStage(%q) = %d, want %d", tt.input, got, tt.expected)
			}
		})
	}
}
