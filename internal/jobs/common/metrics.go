package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// UpdateMetricOutputRef updates a Metric record with the output document reference.
// This is best-effort; callers should decide whether failures are fatal.
func UpdateMetricOutputRef(ctx context.Context, metricDocID, outputType, outputDocID, outputCID string) error {
	if metricDocID == "" || outputType == "" || outputDocID == "" {
		return nil
	}

	client := svcctx.DefraClientFrom(ctx)
	if client == nil {
		return fmt.Errorf("defra client not in context")
	}

	return metrics.UpdateOutputRef(ctx, client, metricDocID, outputType, outputDocID, outputCID)
}
