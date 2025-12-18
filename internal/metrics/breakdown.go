package metrics

import "context"

// BookCost returns the total cost for a book.
func (q *Query) BookCost(ctx context.Context, bookID string) (float64, error) {
	return q.TotalCost(ctx, Filter{BookID: bookID})
}

// StageCost returns the total cost for a stage (across all books).
func (q *Query) StageCost(ctx context.Context, stage string) (float64, error) {
	return q.TotalCost(ctx, Filter{Stage: stage})
}

// BookStageCost returns the total cost for a specific book and stage.
func (q *Query) BookStageCost(ctx context.Context, bookID, stage string) (float64, error) {
	return q.TotalCost(ctx, Filter{BookID: bookID, Stage: stage})
}

// BookStageBreakdown returns cost breakdown by stage for a book.
func (q *Query) BookStageBreakdown(ctx context.Context, bookID string) (map[string]float64, error) {
	metrics, err := q.List(ctx, Filter{BookID: bookID}, 0)
	if err != nil {
		return nil, err
	}

	breakdown := make(map[string]float64)
	for _, m := range metrics {
		breakdown[m.Stage] += m.CostUSD
	}
	return breakdown, nil
}

// CostByModel returns cost breakdown by model.
func (q *Query) CostByModel(ctx context.Context, f Filter) (map[string]float64, error) {
	metrics, err := q.List(ctx, f, 0)
	if err != nil {
		return nil, err
	}

	breakdown := make(map[string]float64)
	for _, m := range metrics {
		breakdown[m.Model] += m.CostUSD
	}
	return breakdown, nil
}

// CostByProvider returns cost breakdown by provider.
func (q *Query) CostByProvider(ctx context.Context, f Filter) (map[string]float64, error) {
	metrics, err := q.List(ctx, f, 0)
	if err != nil {
		return nil, err
	}

	breakdown := make(map[string]float64)
	for _, m := range metrics {
		breakdown[m.Provider] += m.CostUSD
	}
	return breakdown, nil
}

// MetricForOutput returns the metric that produced a specific output version.
func (q *Query) MetricForOutput(ctx context.Context, docID, cid string) (*Metric, error) {
	metrics, err := q.List(ctx, Filter{OutputDocID: docID, OutputCID: cid}, 1)
	if err != nil {
		return nil, err
	}
	if len(metrics) == 0 {
		return nil, nil
	}
	return &metrics[0], nil
}
