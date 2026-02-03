package metrics

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
)

// UpdateOutputRef updates a metric record with output document reference fields.
// outputCID is optional; if empty, only doc/type are updated.
func UpdateOutputRef(ctx context.Context, client *defra.Client, metricDocID, outputType, outputDocID, outputCID string) error {
	if client == nil {
		return fmt.Errorf("defra client is nil")
	}
	if metricDocID == "" || outputType == "" || outputDocID == "" {
		return nil
	}

	update := map[string]any{
		"output_doc_id": outputDocID,
		"output_type":   outputType,
	}
	if outputCID != "" {
		update["output_cid"] = outputCID
	}

	if err := client.Update(ctx, "Metric", metricDocID, update); err != nil {
		return fmt.Errorf("failed to update metric output ref: %w", err)
	}
	return nil
}
