package common

import "github.com/jackzampolin/shelf/internal/prompts/blend"

// FilterOcrQuality filters out garbage OCR outputs that are likely hallucinations.
// This is a port of Python's infra/ocr/quality.py filter_ocr_quality function.
//
// Detection logic:
// 1. Calculate baseline average length from non-paddle providers
// 2. If paddle output is > threshold * baseline, filter it out (likely garbage)
// 3. Special case: if baseline < 100 chars and paddle > 1000, filter paddle
func FilterOcrQuality(outputs []blend.OCROutput, inflationThreshold float64) []blend.OCROutput {
	if len(outputs) <= 1 {
		return outputs
	}

	// Find paddle output and calculate baseline from others
	var paddleIdx int = -1
	var paddleLen int
	var baselineTotal int
	var baselineCount int

	for i, out := range outputs {
		if out.ProviderName == "paddle" {
			paddleIdx = i
			paddleLen = len(out.Text)
		} else {
			baselineTotal += len(out.Text)
			baselineCount++
		}
	}

	// No paddle output, nothing to filter
	if paddleIdx == -1 {
		return outputs
	}

	// No baseline to compare against
	if baselineCount == 0 {
		return outputs
	}

	baselineAvg := float64(baselineTotal) / float64(baselineCount)

	// Special case: near-blank page with paddle hallucination
	if baselineAvg < 100 && paddleLen > 1000 {
		// Filter out paddle
		return append(outputs[:paddleIdx], outputs[paddleIdx+1:]...)
	}

	// Standard inflation check
	if baselineAvg > 0 && float64(paddleLen) > baselineAvg*inflationThreshold {
		// Filter out paddle
		return append(outputs[:paddleIdx], outputs[paddleIdx+1:]...)
	}

	return outputs
}
