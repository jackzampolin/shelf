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
// and returns the blended text. Also updates the page state.
func SaveBlendResult(ctx context.Context, state *PageState, primaryProvider string, parsedJSON any) (string, error) {
	blendResult, err := blend.ParseResult(parsedJSON)
	if err != nil {
		return "", err
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return "", fmt.Errorf("defra sink not in context")
	}

	baseText := state.OcrResults[primaryProvider]
	blendedText := blend.ApplyCorrections(baseText, blendResult.Corrections)

	correctionsJSON, _ := json.Marshal(blendResult.Corrections)

	// Fire-and-forget - no need to block
	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      state.PageDocID,
		Document: map[string]any{
			"blend_markdown":    blendedText,
			"blend_corrections": string(correctionsJSON),
			"blend_confidence":  blendResult.Confidence,
			"blend_complete":    true,
		},
		Op: defra.OpUpdate,
	})

	// Update in-memory state
	state.BlendedText = blendedText
	state.BlendDone = true

	return blendedText, nil
}
