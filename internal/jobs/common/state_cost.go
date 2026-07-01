package common

import (
	"context"
)

// --- Cost Tracking Accessors ---
// Write-through cache: costs are updated when work units complete.
// Lazy load: costs can be loaded from DB on first access if not already cached.

// AddCost adds a cost amount for a stage (thread-safe).
// Called by OnComplete handlers when work units finish.
func (b *BookState) AddCost(stage string, cost float64) {
	if cost <= 0 {
		return
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	b.costsByStage[stage] += cost
	b.totalCost += cost
}

// GetTotalCost returns the total accumulated cost (thread-safe).
func (b *BookState) GetTotalCost() float64 {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.totalCost
}

// GetCostByStage returns the cost for a specific stage (thread-safe).
func (b *BookState) GetCostByStage(stage string) float64 {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.costsByStage[stage]
}

// GetCostsByStage returns a copy of all costs by stage (thread-safe).
func (b *BookState) GetCostsByStage() map[string]float64 {
	b.mu.RLock()
	defer b.mu.RUnlock()
	result := make(map[string]float64, len(b.costsByStage))
	for k, v := range b.costsByStage {
		result[k] = v
	}
	return result
}

// SetCosts sets costs from loaded data (thread-safe).
// Used when loading costs from DB or restoring from checkpoint.
func (b *BookState) SetCosts(costsByStage map[string]float64, totalCost float64) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.costsByStage = make(map[string]float64, len(costsByStage))
	for k, v := range costsByStage {
		b.costsByStage[k] = v
	}
	b.totalCost = totalCost
	b.costsLoaded = true
}

// CostsLoaded returns true if costs have been loaded from DB (thread-safe).
func (b *BookState) CostsLoaded() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.costsLoaded
}

// GetTotalCostWithLazyLoad returns total cost, loading from DB if needed (thread-safe).
// Requires context with DefraClient for DB queries.
func (b *BookState) GetTotalCostWithLazyLoad(ctx context.Context) float64 {
	b.mu.RLock()
	if b.costsLoaded {
		cost := b.totalCost
		b.mu.RUnlock()
		return cost
	}
	b.mu.RUnlock()

	// Need to load from DB - upgrade to write lock
	b.mu.Lock()
	defer b.mu.Unlock()

	// Double-check after acquiring write lock
	if b.costsLoaded {
		return b.totalCost
	}

	// Load costs from DefraDB
	loadBookCostsFromDB(ctx, b)
	return b.totalCost
}
