package metrics

import (
	"context"
	"sort"
	"time"
)

// TotalCost returns the total cost for metrics matching the filter.
func (q *Query) TotalCost(ctx context.Context, f Filter) (float64, error) {
	metrics, err := q.List(ctx, f, 0)
	if err != nil {
		return 0, err
	}

	var total float64
	for _, m := range metrics {
		total += m.CostUSD
	}
	return total, nil
}

// TotalTokens returns the total tokens for metrics matching the filter.
func (q *Query) TotalTokens(ctx context.Context, f Filter) (int, error) {
	metrics, err := q.List(ctx, f, 0)
	if err != nil {
		return 0, err
	}

	var total int
	for _, m := range metrics {
		total += m.TotalTokens
	}
	return total, nil
}

// TotalTime returns the total execution time for metrics matching the filter.
func (q *Query) TotalTime(ctx context.Context, f Filter) (time.Duration, error) {
	metrics, err := q.List(ctx, f, 0)
	if err != nil {
		return 0, err
	}

	var total float64
	for _, m := range metrics {
		total += m.TotalSeconds
	}
	return time.Duration(total * float64(time.Second)), nil
}

// Summary provides a summary of metrics for a filter.
type Summary struct {
	Count          int           `json:"count"`
	TotalCostUSD   float64       `json:"total_cost_usd"`
	TotalTokens    int           `json:"total_tokens"`
	TotalTime      time.Duration `json:"total_time"`
	SuccessCount   int           `json:"success_count"`
	ErrorCount     int           `json:"error_count"`
	AvgCostUSD     float64       `json:"avg_cost_usd"`
	AvgTokens      float64       `json:"avg_tokens"`
	AvgTimeSeconds float64       `json:"avg_time_seconds"`
}

// GetSummary returns a summary of metrics matching the filter.
func (q *Query) GetSummary(ctx context.Context, f Filter) (*Summary, error) {
	metrics, err := q.List(ctx, f, 0)
	if err != nil {
		return nil, err
	}

	s := &Summary{Count: len(metrics)}
	for _, m := range metrics {
		s.TotalCostUSD += m.CostUSD
		s.TotalTokens += m.TotalTokens
		s.TotalTime += time.Duration(m.TotalSeconds * float64(time.Second))
		if m.Success {
			s.SuccessCount++
		} else {
			s.ErrorCount++
		}
	}

	if s.Count > 0 {
		s.AvgCostUSD = s.TotalCostUSD / float64(s.Count)
		s.AvgTokens = float64(s.TotalTokens) / float64(s.Count)
		s.AvgTimeSeconds = s.TotalTime.Seconds() / float64(s.Count)
	}

	return s, nil
}

// DetailedStats provides comprehensive statistics including percentiles and token breakdowns.
type DetailedStats struct {
	// Basic counts
	Count        int `json:"count"`
	SuccessCount int `json:"success_count"`
	ErrorCount   int `json:"error_count"`

	// Cost
	TotalCostUSD float64 `json:"total_cost_usd"`
	AvgCostUSD   float64 `json:"avg_cost_usd"`

	// Latency percentiles (seconds)
	LatencyP50 float64 `json:"latency_p50"`
	LatencyP95 float64 `json:"latency_p95"`
	LatencyP99 float64 `json:"latency_p99"`
	LatencyAvg float64 `json:"latency_avg"`
	LatencyMin float64 `json:"latency_min"`
	LatencyMax float64 `json:"latency_max"`

	// Token stats
	TotalPromptTokens     int `json:"total_prompt_tokens"`
	TotalCompletionTokens int `json:"total_completion_tokens"`
	TotalReasoningTokens  int `json:"total_reasoning_tokens"`
	TotalTokens           int `json:"total_tokens"`

	// Average tokens per call
	AvgPromptTokens     float64 `json:"avg_prompt_tokens"`
	AvgCompletionTokens float64 `json:"avg_completion_tokens"`
	AvgReasoningTokens  float64 `json:"avg_reasoning_tokens"`
	AvgTotalTokens      float64 `json:"avg_total_tokens"`
}

// GetDetailedStats returns detailed statistics including latency percentiles and token breakdowns.
func (q *Query) GetDetailedStats(ctx context.Context, f Filter) (*DetailedStats, error) {
	metrics, err := q.List(ctx, f, 0)
	if err != nil {
		return nil, err
	}

	stats := &DetailedStats{Count: len(metrics)}
	if len(metrics) == 0 {
		return stats, nil
	}

	// Collect latencies for percentile calculation
	var latencies []float64

	for _, m := range metrics {
		// Costs
		stats.TotalCostUSD += m.CostUSD

		// Success/error counts
		if m.Success {
			stats.SuccessCount++
		} else {
			stats.ErrorCount++
		}

		// Token totals
		stats.TotalPromptTokens += m.PromptTokens
		stats.TotalCompletionTokens += m.CompletionTokens
		stats.TotalReasoningTokens += m.ReasoningTokens
		stats.TotalTokens += m.TotalTokens

		// Collect latency for percentile calc
		if m.TotalSeconds > 0 {
			latencies = append(latencies, m.TotalSeconds)
		}
	}

	// Calculate averages
	count := float64(stats.Count)
	stats.AvgCostUSD = stats.TotalCostUSD / count
	stats.AvgPromptTokens = float64(stats.TotalPromptTokens) / count
	stats.AvgCompletionTokens = float64(stats.TotalCompletionTokens) / count
	stats.AvgReasoningTokens = float64(stats.TotalReasoningTokens) / count
	stats.AvgTotalTokens = float64(stats.TotalTokens) / count

	// Calculate latency percentiles
	if len(latencies) > 0 {
		sort.Float64s(latencies)

		// Min/max
		stats.LatencyMin = latencies[0]
		stats.LatencyMax = latencies[len(latencies)-1]

		// Average
		var sum float64
		for _, l := range latencies {
			sum += l
		}
		stats.LatencyAvg = sum / float64(len(latencies))

		// Percentiles
		stats.LatencyP50 = percentile(latencies, 50)
		stats.LatencyP95 = percentile(latencies, 95)
		stats.LatencyP99 = percentile(latencies, 99)
	}

	return stats, nil
}

// percentile calculates the p-th percentile from a sorted slice of values.
func percentile(sorted []float64, p float64) float64 {
	if len(sorted) == 0 {
		return 0
	}
	if len(sorted) == 1 {
		return sorted[0]
	}

	// Calculate the index
	n := float64(len(sorted))
	idx := (p / 100.0) * (n - 1)

	// Interpolate between floor and ceil indices
	lower := int(idx)
	upper := lower + 1
	if upper >= len(sorted) {
		return sorted[len(sorted)-1]
	}

	// Linear interpolation
	weight := idx - float64(lower)
	return sorted[lower]*(1-weight) + sorted[upper]*weight
}

// StageDetailedStats returns detailed stats grouped by stage for a book.
func (q *Query) StageDetailedStats(ctx context.Context, bookID string) (map[string]*DetailedStats, error) {
	// Get all metrics for this book
	metrics, err := q.List(ctx, Filter{BookID: bookID}, 0)
	if err != nil {
		return nil, err
	}

	// Group by stage
	byStage := make(map[string][]Metric)
	for _, m := range metrics {
		if m.Stage != "" {
			byStage[m.Stage] = append(byStage[m.Stage], m)
		}
	}

	// Calculate stats per stage
	result := make(map[string]*DetailedStats)
	for stage, stageMetrics := range byStage {
		stats := &DetailedStats{Count: len(stageMetrics)}
		if len(stageMetrics) == 0 {
			result[stage] = stats
			continue
		}

		var latencies []float64
		for _, m := range stageMetrics {
			stats.TotalCostUSD += m.CostUSD
			if m.Success {
				stats.SuccessCount++
			} else {
				stats.ErrorCount++
			}
			stats.TotalPromptTokens += m.PromptTokens
			stats.TotalCompletionTokens += m.CompletionTokens
			stats.TotalReasoningTokens += m.ReasoningTokens
			stats.TotalTokens += m.TotalTokens
			if m.TotalSeconds > 0 {
				latencies = append(latencies, m.TotalSeconds)
			}
		}

		// Averages
		count := float64(stats.Count)
		stats.AvgCostUSD = stats.TotalCostUSD / count
		stats.AvgPromptTokens = float64(stats.TotalPromptTokens) / count
		stats.AvgCompletionTokens = float64(stats.TotalCompletionTokens) / count
		stats.AvgReasoningTokens = float64(stats.TotalReasoningTokens) / count
		stats.AvgTotalTokens = float64(stats.TotalTokens) / count

		// Latency percentiles
		if len(latencies) > 0 {
			sort.Float64s(latencies)
			stats.LatencyMin = latencies[0]
			stats.LatencyMax = latencies[len(latencies)-1]
			var sum float64
			for _, l := range latencies {
				sum += l
			}
			stats.LatencyAvg = sum / float64(len(latencies))
			stats.LatencyP50 = percentile(latencies, 50)
			stats.LatencyP95 = percentile(latencies, 95)
			stats.LatencyP99 = percentile(latencies, 99)
		}

		result[stage] = stats
	}

	return result, nil
}
