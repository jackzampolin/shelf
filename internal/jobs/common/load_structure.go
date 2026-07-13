package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/svcctx"
)

// LoadStructureChapters loads all Chapter records for a book from DefraDB.
// This populates book.StructureChapters for crash recovery during structure phase.
func LoadStructureChapters(ctx context.Context, book *BookState) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	logger := svcctx.LoggerFrom(ctx)

	query := fmt.Sprintf(`{
		Chapter(filter: {_bookID: {_eq: "%s"}}, order: {sort_order: ASC}) {
			_docID
			unique_key
			entry_id
			sort_order
			title
			level
			level_name
			entry_number
			start_page
			end_page
			parent_id
			source
			_toc_entryID
			matter_type
			classification_reasoning
			content_type
			audio_include
			audio_include_reasoning
			mechanical_text
			polished_text
			edits_applied_json
			word_count
			extract_complete
			polish_complete
			polish_failed
			polish_retries
		}
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query chapters: %w", err)
	}

	rawChapters, ok := resp.Data["Chapter"].([]any)
	if !ok || len(rawChapters) == 0 {
		if logger != nil {
			logger.Debug("no structure chapters found", "book_id", book.BookID)
		}
		return nil
	}

	var chapters []*ChapterState
	for _, c := range rawChapters {
		data, ok := c.(map[string]any)
		if !ok {
			continue
		}

		chapter := &ChapterState{}

		if docID, ok := data["_docID"].(string); ok {
			chapter.DocID = docID
		}
		if uniqueKey, ok := data["unique_key"].(string); ok {
			chapter.UniqueKey = uniqueKey
		}
		if entryID, ok := data["entry_id"].(string); ok {
			chapter.EntryID = entryID
		}
		if sortOrder, ok := data["sort_order"].(float64); ok {
			chapter.SortOrder = int(sortOrder)
		}
		if title, ok := data["title"].(string); ok {
			chapter.Title = title
		}
		if level, ok := data["level"].(float64); ok {
			chapter.Level = int(level)
		}
		if levelName, ok := data["level_name"].(string); ok {
			chapter.LevelName = levelName
		}
		if entryNumber, ok := data["entry_number"].(string); ok {
			chapter.EntryNumber = entryNumber
		}
		if startPage, ok := data["start_page"].(float64); ok {
			chapter.StartPage = int(startPage)
		}
		if endPage, ok := data["end_page"].(float64); ok {
			chapter.EndPage = int(endPage)
		}
		if parentID, ok := data["parent_id"].(string); ok {
			chapter.ParentID = parentID
		}
		if source, ok := data["source"].(string); ok {
			chapter.Source = source
		}
		if tocEntryID, ok := data["_toc_entryID"].(string); ok {
			chapter.TocEntryID = tocEntryID
		}
		if matterType, ok := data["matter_type"].(string); ok {
			chapter.MatterType = matterType
		}
		if reasoning, ok := data["classification_reasoning"].(string); ok {
			chapter.ClassifyReasoning = reasoning
		}
		if contentType, ok := data["content_type"].(string); ok {
			chapter.ContentType = contentType
		}
		if include, ok := data["audio_include"].(bool); ok {
			chapter.AudioInclude = include
		} else if chapter.MatterType != "" {
			// Backwards compat for older books without audio_include persisted.
			switch chapter.MatterType {
			case "back_matter":
				chapter.AudioInclude = false
			default:
				chapter.AudioInclude = true
			}
		}
		if reasoning, ok := data["audio_include_reasoning"].(string); ok {
			chapter.AudioIncludeReasoning = reasoning
		}
		if mechText, ok := data["mechanical_text"].(string); ok {
			chapter.MechanicalText = mechText
		}
		if polText, ok := data["polished_text"].(string); ok {
			chapter.PolishedText = polText
		}
		if editsJSON, ok := data["edits_applied_json"].(string); ok {
			chapter.EditsAppliedJSON = editsJSON
		}
		if wordCount, ok := data["word_count"].(float64); ok {
			chapter.WordCount = int(wordCount)
		}
		if extractDone, ok := data["extract_complete"].(bool); ok {
			chapter.ExtractDone = extractDone
		}
		if polishDone, ok := data["polish_complete"].(bool); ok {
			chapter.PolishDone = polishDone
		}
		if polishFailed, ok := data["polish_failed"].(bool); ok {
			chapter.PolishFailed = polishFailed
		}

		// Validate chapter before adding
		if chapter.DocID == "" {
			continue
		}
		// Validate page boundaries
		if chapter.StartPage < 1 {
			if logger != nil {
				logger.Warn("skipping chapter with invalid start_page",
					"doc_id", chapter.DocID,
					"start_page", chapter.StartPage,
					"title", chapter.Title)
			}
			continue
		}
		if chapter.EndPage > 0 && chapter.EndPage < chapter.StartPage {
			if logger != nil {
				logger.Warn("skipping chapter with end_page < start_page",
					"doc_id", chapter.DocID,
					"start_page", chapter.StartPage,
					"end_page", chapter.EndPage,
					"title", chapter.Title)
			}
			continue
		}
		chapters = append(chapters, chapter)
	}

	book.SetStructureChapters(chapters)

	// Also rebuild the classifications map from chapters
	classifications := make(map[string]string)
	reasonings := make(map[string]string)
	for _, ch := range chapters {
		if ch.MatterType != "" {
			classifications[ch.EntryID] = ch.MatterType
		}
		if ch.AudioIncludeReasoning != "" {
			reasonings[ch.EntryID] = ch.AudioIncludeReasoning
		} else if ch.ClassifyReasoning != "" {
			reasonings[ch.EntryID] = ch.ClassifyReasoning
		}
	}
	book.SetStructureClassifications(classifications)
	book.SetStructureClassifyReasonings(reasonings)

	if logger != nil {
		logger.Debug("loaded structure chapters",
			"book_id", book.BookID,
			"count", len(chapters))
	}

	return nil
}
