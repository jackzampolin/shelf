package job

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateMetadataWorkUnit creates a metadata extraction work unit.
func (j *Job) CreateMetadataWorkUnit(ctx context.Context) *jobs.WorkUnit {
	// Load first 20 pages of blended text
	pages, err := j.LoadPagesForMetadata(ctx, LabelThresholdForBookOps)
	if err != nil || len(pages) == 0 {
		return nil
	}

	bookText := metadata.PrepareBookText(pages, LabelThresholdForBookOps)
	if bookText == "" {
		return nil
	}

	unitID := uuid.New().String()
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType: "metadata",
	})

	unit := metadata.CreateWorkUnit(metadata.Input{
		BookText:             bookText,
		SystemPromptOverride: j.GetPrompt(metadata.SystemPromptKey),
	})
	unit.ID = unitID
	unit.Provider = j.Book.MetadataProvider
	unit.JobID = j.RecordID

	metrics := j.MetricsFor()
	metrics.ItemKey = "metadata"
	metrics.PromptKey = metadata.SystemPromptKey
	metrics.PromptCID = j.GetPromptCID(metadata.SystemPromptKey)
	unit.Metrics = metrics

	return unit
}

// LoadPagesForMetadata loads page data for metadata extraction.
func (j *Job) LoadPagesForMetadata(ctx context.Context, maxPages int) ([]metadata.Page, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}, order: {page_num: ASC}) {
			page_num
			blend_markdown
		}
	}`, j.Book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	rawPages, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil, nil
	}

	var pages []metadata.Page
	for i, p := range rawPages {
		if i >= maxPages {
			break
		}
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}

		var mp metadata.Page
		if pn, ok := page["page_num"].(float64); ok {
			mp.PageNum = int(pn)
		}
		if bm, ok := page["blend_markdown"].(string); ok {
			mp.BlendMarkdown = bm
		}
		pages = append(pages, mp)
	}

	return pages, nil
}

// HandleMetadataComplete processes metadata extraction completion.
func (j *Job) HandleMetadataComplete(ctx context.Context, result jobs.WorkResult) error {
	if result.ChatResult == nil || result.ChatResult.ParsedJSON == nil {
		return nil
	}

	metadataResult, err := metadata.ParseResult(result.ChatResult.ParsedJSON)
	if err != nil {
		return fmt.Errorf("failed to parse metadata result: %w", err)
	}

	if err := j.SaveMetadataResult(ctx, *metadataResult); err != nil {
		return fmt.Errorf("failed to save metadata: %w", err)
	}

	j.Book.Metadata.Complete()
	return nil
}

// SaveMetadataResult saves the metadata result to the Book record.
func (j *Job) SaveMetadataResult(ctx context.Context, result metadata.Result) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	update := map[string]any{
		"title":             result.Title,
		"metadata_complete": true,
	}

	if len(result.Authors) > 0 {
		update["author"] = result.Authors[0]
		update["authors"] = result.Authors // DefraDB handles [String] arrays directly
	}

	if result.ISBN != nil {
		update["isbn"] = *result.ISBN
	}
	if result.Publisher != nil {
		update["publisher"] = *result.Publisher
	}
	if result.PublicationYear != nil {
		update["publication_year"] = *result.PublicationYear
	}
	if result.Description != nil {
		update["description"] = *result.Description
	}
	if len(result.Subjects) > 0 {
		update["subjects"] = result.Subjects // DefraDB handles [String] arrays directly
	}

	// Fire-and-forget - no need to block
	sink.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      j.Book.BookID,
		Document:   update,
		Op:         defra.OpUpdate,
	})
	return nil
}
