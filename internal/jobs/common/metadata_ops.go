package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// LoadPagesForMetadata loads page data for metadata extraction from DefraDB.
func LoadPagesForMetadata(ctx context.Context, bookID string, maxPages int) ([]metadata.Page, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}, order: {page_num: ASC}) {
			page_num
			blend_markdown
		}
	}`, bookID)

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

// SaveMetadataResult saves the metadata result to the Book record in DefraDB.
func SaveMetadataResult(ctx context.Context, bookID string, result metadata.Result) error {
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
		update["authors"] = result.Authors
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
		update["subjects"] = result.Subjects
	}

	// Fire-and-forget - no need to block
	sink.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      bookID,
		Document:   update,
		Op:         defra.OpUpdate,
	})
	return nil
}
