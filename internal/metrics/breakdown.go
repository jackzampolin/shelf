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

// CostByOperationType returns cost breakdown by operation type, derived from item_key.
// item_key format: "page_XXXX_<type>" where type is provider name (mistral, paddle) for OCR
// or operation name (blend, label) for LLM operations.
func (q *Query) CostByOperationType(ctx context.Context, f Filter) (map[string]float64, error) {
	metrics, err := q.List(ctx, f, 0)
	if err != nil {
		return nil, err
	}

	breakdown := make(map[string]float64)
	for _, m := range metrics {
		// Parse item_key to get operation type
		// Format: page_XXXX_<type> or just <type>
		opType := parseOperationType(m.ItemKey, m.Provider)
		breakdown[opType] += m.CostUSD
	}
	return breakdown, nil
}

// CostByOCRProvider returns OCR cost breakdown by provider (mistral, paddle, etc).
func (q *Query) CostByOCRProvider(ctx context.Context, f Filter) (map[string]float64, error) {
	metrics, err := q.List(ctx, f, 0)
	if err != nil {
		return nil, err
	}

	breakdown := make(map[string]float64)
	for _, m := range metrics {
		// OCR metrics have item_key like "page_0277_mistral" where the provider is in the key
		opType := parseOperationType(m.ItemKey, m.Provider)
		// Only include OCR operations (not blend/label)
		if opType != "blend" && opType != "label" && opType != "metadata" && opType != "toc" {
			breakdown[opType] += m.CostUSD
		}
	}
	return breakdown, nil
}

// parseOperationType extracts the operation type from item_key.
// item_key formats:
// - "page_0277_mistral" -> "mistral" (OCR)
// - "page_0067_blend" -> "blend"
// - "page_0014_label" -> "label"
// - "metadata" -> "metadata"
// - "toc_finder" -> "toc"
// - "toc_extract" -> "toc"
func parseOperationType(itemKey, provider string) string {
	if itemKey == "" {
		return provider
	}

	// Split by underscore and get the last part
	parts := splitItemKey(itemKey)
	if len(parts) >= 3 {
		// page_0277_mistral -> mistral
		return parts[len(parts)-1]
	}
	if len(parts) == 2 {
		// toc_finder -> toc, toc_extract -> toc
		return parts[0]
	}
	if len(parts) == 1 {
		// metadata -> metadata
		return parts[0]
	}
	return provider
}

func splitItemKey(s string) []string {
	var parts []string
	current := ""
	for _, c := range s {
		if c == '_' {
			if current != "" {
				parts = append(parts, current)
				current = ""
			}
		} else {
			current += string(c)
		}
	}
	if current != "" {
		parts = append(parts, current)
	}
	return parts
}
