package page_processing

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/pipeline"
	pjob "github.com/jackzampolin/shelf/internal/pipeline/stages/page_processing/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// Stage handles per-page processing: OCR -> Blend -> Label.
// Also triggers book-level operations: ToC finding, ToC extraction, metadata.
type Stage struct {
	// Provider configuration (not services - those come from context)
	ocrProviders     []string // e.g., ["mistral", "paddle"]
	blendProvider    string   // LLM provider for blending
	labelProvider    string   // LLM provider for labeling
	metadataProvider string   // LLM provider for metadata extraction
	tocProvider      string   // LLM provider for ToC operations
}

// Config configures the stage.
type Config struct {
	OcrProviders     []string
	BlendProvider    string
	LabelProvider    string
	MetadataProvider string
	TocProvider      string
}

// NewStage creates a new page processing stage.
func NewStage(cfg Config) *Stage {
	return &Stage{
		ocrProviders:     cfg.OcrProviders,
		blendProvider:    cfg.BlendProvider,
		labelProvider:    cfg.LabelProvider,
		metadataProvider: cfg.MetadataProvider,
		tocProvider:      cfg.TocProvider,
	}
}

func (s *Stage) Name() string           { return "page-processing" }
func (s *Stage) Dependencies() []string { return nil }
func (s *Stage) Icon() string           { return "📄" }
func (s *Stage) Description() string {
	return "Process pages through OCR, blend, label, ToC, and metadata extraction"
}

func (s *Stage) RequiredCollections() []string {
	return []string{"Book", "Page", "ToC"}
}

// Status represents the status of page processing for a book.
type Status struct {
	TotalPages       int  `json:"total_pages"`
	OcrComplete      int  `json:"ocr_complete"`
	BlendComplete    int  `json:"blend_complete"`
	LabelComplete    int  `json:"label_complete"`
	MetadataComplete bool `json:"metadata_complete"`
	TocFound         bool `json:"toc_found"`
	TocExtracted     bool `json:"toc_extracted"`
}

func (st *Status) IsComplete() bool {
	allPagesComplete := st.LabelComplete >= st.TotalPages
	return allPagesComplete && st.MetadataComplete && st.TocExtracted
}

func (st *Status) Data() any {
	return st
}

func (s *Stage) GetStatus(ctx context.Context, bookID string) (pipeline.StageStatus, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	// Query book for total pages and metadata status
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			page_count
			metadata_complete
		}
	}`, bookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query book: %w", err)
	}

	status := &Status{}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if book, ok := books[0].(map[string]any); ok {
			if pc, ok := book["page_count"].(float64); ok {
				status.TotalPages = int(pc)
			}
			if mc, ok := book["metadata_complete"].(bool); ok {
				status.MetadataComplete = mc
			}
		}
	}

	// Query page completion counts
	pageQuery := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}) {
			ocr_complete
			blend_complete
			label_complete
		}
	}`, bookID)

	pageResp, err := defraClient.Execute(ctx, pageQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query pages: %w", err)
	}

	if pages, ok := pageResp.Data["Page"].([]any); ok {
		for _, p := range pages {
			page, ok := p.(map[string]any)
			if !ok {
				continue
			}
			if ocrComplete, ok := page["ocr_complete"].(bool); ok && ocrComplete {
				status.OcrComplete++
			}
			if blendComplete, ok := page["blend_complete"].(bool); ok && blendComplete {
				status.BlendComplete++
			}
			if labelComplete, ok := page["label_complete"].(bool); ok && labelComplete {
				status.LabelComplete++
			}
		}
	}

	// Query ToC status
	tocQuery := fmt.Sprintf(`{
		ToC(filter: {book_id: {_eq: "%s"}}) {
			toc_found
			extract_complete
		}
	}`, bookID)

	tocResp, err := defraClient.Execute(ctx, tocQuery, nil)
	if err == nil {
		if tocs, ok := tocResp.Data["ToC"].([]any); ok && len(tocs) > 0 {
			if toc, ok := tocs[0].(map[string]any); ok {
				if found, ok := toc["toc_found"].(bool); ok {
					status.TocFound = found
				}
				if extracted, ok := toc["extract_complete"].(bool); ok {
					status.TocExtracted = extracted
				}
			}
		}
	}

	return status, nil
}

func (s *Stage) CreateJob(ctx context.Context, bookID string, opts pipeline.StageOptions) (jobs.Job, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		return nil, fmt.Errorf("home directory not in context")
	}

	// Get book info
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			page_count
		}
	}`, bookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query book: %w", err)
	}

	var totalPages int
	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if book, ok := books[0].(map[string]any); ok {
			if pc, ok := book["page_count"].(float64); ok {
				totalPages = int(pc)
			}
		}
	}

	if totalPages == 0 {
		return nil, fmt.Errorf("book %s has no pages", bookID)
	}

	// Job accesses services via svcctx from context passed to Start/OnComplete
	return pjob.New(pjob.Config{
		BookID:           bookID,
		TotalPages:       totalPages,
		HomeDir:          homeDir,
		OcrProviders:     s.ocrProviders,
		BlendProvider:    s.blendProvider,
		LabelProvider:    s.labelProvider,
		MetadataProvider: s.metadataProvider,
		TocProvider:      s.tocProvider,
	}), nil
}
