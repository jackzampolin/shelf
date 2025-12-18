package metrics

import (
	"context"
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
