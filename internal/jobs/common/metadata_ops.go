package common

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// MetadataPageCount is the number of pages to use for metadata extraction.
const MetadataPageCount = 20

// CreateMetadataWorkUnit creates a metadata extraction work unit.
// Returns nil if no pages are available for metadata extraction.
// The caller is responsible for registering the work unit with their tracker.
func CreateMetadataWorkUnit(ctx context.Context, jc JobContext) (*jobs.WorkUnit, string) {
	book := jc.GetBook()
	logger := svcctx.LoggerFrom(ctx)

	// Load first N pages of blended text from BookState (in-memory)
	pages := LoadPagesForMetadataFromState(book, MetadataPageCount)

	// Fall back to DB if in-memory state doesn't have blend markdown cached
	// (happens after job reload from DB)
	if len(pages) == 0 {
		pages = LoadPagesForMetadataFromDB(ctx, book.BookID, MetadataPageCount)
	}

	if len(pages) == 0 {
		if logger != nil {
			logger.Debug("no pages available for metadata extraction",
				"book_id", book.BookID)
		}
		return nil, ""
	}

	bookText := metadata.PrepareBookText(pages, MetadataPageCount)
	if bookText == "" {
		if logger != nil {
			logger.Debug("no book text available for metadata extraction",
				"book_id", book.BookID)
		}
		return nil, ""
	}

	unitID := uuid.New().String()

	unit := metadata.CreateWorkUnit(metadata.Input{
		BookText:             bookText,
		SystemPromptOverride: book.GetPrompt(metadata.SystemPromptKey),
		UserPromptOverride:   book.GetPrompt(metadata.UserPromptKey),
	})
	unit.ID = unitID
	unit.Provider = book.MetadataProvider
	unit.JobID = jc.ID()
	unit.Priority = jobs.PriorityForStage("metadata")

	unit.Metrics = &jobs.WorkUnitMetrics{
		BookID:    book.BookID,
		Stage:     "metadata",
		ItemKey:   "metadata",
		PromptKey: metadata.SystemPromptKey,
		PromptCID: book.GetPromptCID(metadata.SystemPromptKey),
	}

	return unit, unitID
}

// LoadPagesForMetadataFromState loads page data for metadata extraction.
// First tries in-memory state, then falls back to querying DefraDB.
func LoadPagesForMetadataFromState(book *BookState, maxPages int) []metadata.Page {
	var pages []metadata.Page

	// Iterate through pages in order
	for pageNum := 1; pageNum <= book.TotalPages && len(pages) < maxPages; pageNum++ {
		state := book.GetPage(pageNum)
		if state == nil {
			continue
		}

		blendMarkdown := state.GetBlendedText()
		if blendMarkdown == "" {
			continue
		}

		pages = append(pages, metadata.Page{
			PageNum:       pageNum,
			BlendMarkdown: blendMarkdown,
		})
	}

	return pages
}

// LoadPagesForMetadataFromDB loads page data for metadata extraction directly from DefraDB.
// Use this when blend markdown isn't cached in memory (e.g., after job reload).
func LoadPagesForMetadataFromDB(ctx context.Context, bookID string, maxPages int) []metadata.Page {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, blend_complete: {_eq: true}}, order: {page_num: ASC}, limit: %d) {
			page_num
			blend_markdown
		}
	}`, bookID, maxPages)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil
	}

	pagesData, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil
	}

	var pages []metadata.Page
	for _, p := range pagesData {
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}

		pageNum := 0
		if pn, ok := page["page_num"].(float64); ok {
			pageNum = int(pn)
		}
		blendMarkdown, _ := page["blend_markdown"].(string)

		if pageNum > 0 && blendMarkdown != "" {
			pages = append(pages, metadata.Page{
				PageNum:       pageNum,
				BlendMarkdown: blendMarkdown,
			})
		}
	}

	return pages
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
