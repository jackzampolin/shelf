package common

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/prompts/blend"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// HeadingItem represents a markdown heading extracted from page content.
type HeadingItem struct {
	Level      int    `json:"level"`
	Text       string `json:"text"`
	LineNumber int    `json:"line_number"`
}

// headingPattern matches markdown headings (# through ######).
var headingPattern = regexp.MustCompile(`^(#{1,6})\s+(.+)$`)

// alphanumPattern checks if text contains at least one alphanumeric character.
var alphanumPattern = regexp.MustCompile(`[a-zA-Z0-9]`)

// ExtractHeadings extracts markdown headings from text.
// Returns a slice of HeadingItem for each heading found.
func ExtractHeadings(markdown string) []HeadingItem {
	var headings []HeadingItem
	for lineNum, line := range strings.Split(markdown, "\n") {
		match := headingPattern.FindStringSubmatch(strings.TrimSpace(line))
		if match == nil {
			continue
		}
		text := strings.TrimSpace(match[2])
		// Only include headings with actual alphanumeric content
		if alphanumPattern.MatchString(text) {
			headings = append(headings, HeadingItem{
				Level:      len(match[1]),
				Text:       text,
				LineNumber: lineNum + 1, // 1-indexed
			})
		}
	}
	return headings
}

// CreateBlendWorkUnit creates a blend LLM work unit.
// Returns nil if no OCR outputs are available.
// The caller is responsible for registering the work unit with their tracker.
func CreateBlendWorkUnit(jc JobContext, pageNum int, state *PageState) (*jobs.WorkUnit, string) {
	book := jc.GetBook()

	var outputs []blend.OCROutput
	for _, provider := range book.OcrProviders {
		if text, ok := state.GetOcrResult(provider); ok && text != "" {
			outputs = append(outputs, blend.OCROutput{
				ProviderName: provider,
				Text:         text,
			})
		}
	}

	if len(outputs) == 0 {
		return nil, ""
	}

	// Filter out garbage OCR (hallucinated repeated characters)
	outputs = FilterOcrQuality(outputs, 1.75)

	unitID := uuid.New().String()

	unit := blend.CreateWorkUnit(blend.Input{
		OCROutputs:           outputs,
		SystemPromptOverride: book.GetPrompt(blend.SystemPromptKey),
		UserPromptOverride:   book.GetPrompt(blend.UserPromptKey),
	})
	unit.ID = unitID
	unit.Provider = book.BlendProvider
	unit.JobID = jc.ID()

	unit.Metrics = &jobs.WorkUnitMetrics{
		BookID:    book.BookID,
		Stage:     jc.Type(),
		ItemKey:   fmt.Sprintf("page_%04d_blend", pageNum),
		PromptKey: blend.SystemPromptKey,
		PromptCID: book.GetPromptCID(blend.SystemPromptKey),
	}

	return unit, unitID
}

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

	// Extract headings from blended markdown (mechanical extraction, no LLM)
	headings := ExtractHeadings(blendedText)
	var headingsJSON string
	if len(headings) > 0 {
		headingsBytes, err := json.Marshal(headings)
		if err != nil {
			return "", fmt.Errorf("failed to marshal headings: %w", err)
		}
		headingsJSON = string(headingsBytes)
	}

	// Build update document
	update := map[string]any{
		"blend_markdown":    blendedText,
		"blend_corrections": string(correctionsJSON),
		"blend_confidence":  blendResult.Confidence,
		"blend_complete":    true,
	}
	if headingsJSON != "" {
		update["headings"] = headingsJSON
	}

	// Fire-and-forget write - sink batches and logs errors internally
	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      state.GetPageDocID(),
		Document:   update,
		Op:         defra.OpUpdate,
	})

	// Update in-memory state (thread-safe)
	state.SetBlendResult(blendedText)

	return blendedText, nil
}
