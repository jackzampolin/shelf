package common

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/prompts/blend"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// SaveBlendResult parses the blend result, applies corrections, persists to DefraDB,
// and returns the blended text. Also updates the page state (thread-safe).
func SaveBlendResult(ctx context.Context, state *PageState, primaryProvider string, parsedJSON any) (string, error) {
	blendResult, err := blend.ParseResult(parsedJSON)
	if err != nil {
		return "", err
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return "", fmt.Errorf("defra sink not in context")
	}

	baseText, ok := state.GetOcrResult(primaryProvider)
	if !ok {
		return "", fmt.Errorf("primary provider %q OCR result not found for page %s", primaryProvider, state.GetPageDocID())
	}
	blendedText := blend.ApplyCorrections(baseText, blendResult.Corrections)

	correctionsJSON, err := json.Marshal(blendResult.Corrections)
	if err != nil {
		return "", fmt.Errorf("failed to marshal corrections: %w", err)
	}

	// Fire-and-forget write - sink batches and logs errors internally
	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      state.GetPageDocID(),
		Document: map[string]any{
			"blend_markdown":    blendedText,
			"blend_corrections": string(correctionsJSON),
			"blend_confidence":  blendResult.Confidence,
			"blend_complete":    true,
		},
		Op: defra.OpUpdate,
	})

	// Update in-memory state (thread-safe)
	state.SetBlendResult(blendedText)

	return blendedText, nil
}
