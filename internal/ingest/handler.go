package ingest

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"

	"github.com/pdfcpu/pdfcpu/pkg/api"
	"github.com/pdfcpu/pdfcpu/pkg/pdfcpu/model"

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

// extractSinglePage extracts a single page from a PDF and writes it to the output directory.
func extractSinglePage(ctx context.Context, req PageExtractRequest) (string, error) {
	// Check for cancellation
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	default:
	}

	conf := model.NewDefaultConfiguration()
	conf.ValidationMode = model.ValidationRelaxed

	// Try to decrypt to remove permission restrictions
	workingPath, err := decryptPDF(req.PDFPath, conf)
	if err != nil {
		return "", fmt.Errorf("failed to prepare PDF: %w", err)
	}
	if workingPath != req.PDFPath {
		defer os.Remove(workingPath)
	}

	// Create temp directory for extraction
	tmpDir, err := os.MkdirTemp("", "shelf-page-*")
	if err != nil {
		return "", fmt.Errorf("failed to create temp dir: %w", err)
	}
	defer os.RemoveAll(tmpDir)

	// Extract just this page
	pages := []string{strconv.Itoa(req.PageNum)}
	if err := api.ExtractImagesFile(workingPath, tmpDir, pages, conf); err != nil {
		return "", fmt.Errorf("pdfcpu extract failed: %w", err)
	}

	// Read extracted file (there should be exactly one)
	entries, err := os.ReadDir(tmpDir)
	if err != nil {
		return "", fmt.Errorf("failed to read temp dir: %w", err)
	}

	// Filter out directories
	var files []os.DirEntry
	for _, e := range entries {
		if !e.IsDir() {
			files = append(files, e)
		}
	}

	if len(files) == 0 {
		return "", fmt.Errorf("no image extracted for page %d", req.PageNum)
	}

	// Sort files to get consistent ordering
	sort.Slice(files, func(i, j int) bool {
		return files[i].Name() < files[j].Name()
	})

	// Read the extracted image
	srcPath := filepath.Join(tmpDir, files[0].Name())
	data, err := os.ReadFile(srcPath)
	if err != nil {
		return "", fmt.Errorf("failed to read extracted image: %w", err)
	}

	// Write to destination with sequential naming
	dstPath := filepath.Join(req.OutputDir, fmt.Sprintf("page_%04d.png", req.OutputNum))
	if err := os.WriteFile(dstPath, data, 0o644); err != nil {
		return "", fmt.Errorf("failed to write page image: %w", err)
	}

	return dstPath, nil
}
