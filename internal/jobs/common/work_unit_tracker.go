package common

import "sync"

// WorkUnitTracker provides generic work unit tracking with built-in synchronization.
// T is the job-specific WorkUnitInfo type.
//
// This allows each job to define its own WorkUnitInfo struct with the
// fields it needs (e.g., PageNum, Provider, RetryCount) while sharing
// the tracking implementation.
//
// All methods are thread-safe and can be called concurrently.
//
// Usage:
//
//	type WorkUnitInfo struct {
//	    PageNum    int
//	    UnitType   string
//	    RetryCount int
//	}
//
//	tracker := common.NewWorkUnitTracker[WorkUnitInfo]()
//	tracker.Register("unit-123", WorkUnitInfo{PageNum: 1, UnitType: "ocr"})
type WorkUnitTracker[T any] struct {
	mu    sync.RWMutex
	units map[string]T
}

// NewWorkUnitTracker creates a new tracker with an initialized map.
func NewWorkUnitTracker[T any]() *WorkUnitTracker[T] {
	return &WorkUnitTracker[T]{
		units: make(map[string]T),
	}
}

// Register registers a pending work unit.
func (t *WorkUnitTracker[T]) Register(unitID string, info T) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.units[unitID] = info
}

// Get gets a pending work unit without removing it.
func (t *WorkUnitTracker[T]) Get(unitID string) (T, bool) {
	t.mu.RLock()
	defer t.mu.RUnlock()
	info, ok := t.units[unitID]
	return info, ok
}

// Remove removes a pending work unit.
func (t *WorkUnitTracker[T]) Remove(unitID string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	delete(t.units, unitID)
}

// GetAndRemove gets and removes a pending work unit atomically.
func (t *WorkUnitTracker[T]) GetAndRemove(unitID string) (T, bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	info, ok := t.units[unitID]
	if ok {
		delete(t.units, unitID)
	}
	return info, ok
}

// Count returns the number of pending work units.
func (t *WorkUnitTracker[T]) Count() int {
	t.mu.RLock()
	defer t.mu.RUnlock()
	return len(t.units)
}
