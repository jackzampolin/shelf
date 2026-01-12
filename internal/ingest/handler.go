package ingest

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	"github.com/jackzampolin/shelf/internal/jobs"
)

// ExtractPageHandler returns a CPUTaskHandler that extracts a single page from a PDF.
// This handler is registered on CPU workers to process page extraction work units.
func ExtractPageHandler() jobs.CPUTaskHandler {
	return func(ctx context.Context, req *jobs.CPUWorkRequest) (*jobs.CPUWorkResult, error) {
		// Type assert the data
		pageReq, ok := req.Data.(PageExtractRequest)
		if !ok {
			// Try map conversion (happens when deserializing from JSON)
			if m, ok := req.Data.(map[string]any); ok {
				pageReq = PageExtractRequest{
					PDFPath:   m["PDFPath"].(string),
					PageNum:   int(m["PageNum"].(float64)),
					OutputNum: int(m["OutputNum"].(float64)),
					OutputDir: m["OutputDir"].(string),
				}
			} else {
				return nil, fmt.Errorf("invalid data type for extract-page task: %T", req.Data)
			}
		}

		// Extract the page
		outputPath, err := extractSinglePage(ctx, pageReq)
		if err != nil {
			return nil, err
		}

		return &jobs.CPUWorkResult{
			Data: PageExtractResult{
				OutputPath: outputPath,
				PageNum:    pageReq.OutputNum,
			},
		}, nil
	}
}

// extractSinglePage renders a single page from a PDF using pdftoppm (poppler-utils).
// This renders the page correctly, unlike pdfcpu.ExtractImagesFile which extracts
// embedded image objects whose internal numbering may not match page order.
func extractSinglePage(ctx context.Context, req PageExtractRequest) (string, error) {
	// Check for cancellation
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	default:
	}

	// Create temp directory for output
	tmpDir, err := os.MkdirTemp("", "shelf-page-*")
	if err != nil {
		return "", fmt.Errorf("failed to create temp dir: %w", err)
	}
	defer os.RemoveAll(tmpDir)

	// Output prefix for pdftoppm
	outputPrefix := filepath.Join(tmpDir, "page")

	// Run pdftoppm to render the page
	// -png: output PNG format
	// -f N: first page to render
	// -l N: last page to render
	// -r 300: resolution in DPI (matches reasonable quality for OCR)
	// -singlefile: don't add page number suffix (we handle naming ourselves)
	pageStr := fmt.Sprintf("%d", req.PageNum)
	cmd := exec.CommandContext(ctx, "pdftoppm",
		"-png",
		"-f", pageStr,
		"-l", pageStr,
		"-r", "300",
		"-singlefile",
		req.PDFPath,
		outputPrefix,
	)

	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("pdftoppm failed: %w (output: %s)", err, string(output))
	}

	// pdftoppm with -singlefile creates: <prefix>.png
	srcPath := outputPrefix + ".png"
	if _, err := os.Stat(srcPath); err != nil {
		return "", fmt.Errorf("pdftoppm did not create expected output: %w", err)
	}

	// Read the rendered image
	data, err := os.ReadFile(srcPath)
	if err != nil {
		return "", fmt.Errorf("failed to read rendered image: %w", err)
	}

	// Write to destination with sequential naming
	dstPath := filepath.Join(req.OutputDir, fmt.Sprintf("page_%04d.png", req.OutputNum))
	if err := os.WriteFile(dstPath, data, 0o644); err != nil {
		return "", fmt.Errorf("failed to write page image: %w", err)
	}

	return dstPath, nil
}
