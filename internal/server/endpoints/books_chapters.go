package endpoints

import (
	"fmt"
	"net/http"
	"sort"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// Chapter represents a chapter in the book structure.
type Chapter struct {
	ID                      string `json:"id"`
	EntryID                 string `json:"entry_id,omitempty"`
	Title                   string `json:"title"`
	Level                   int    `json:"level"`
	LevelName               string `json:"level_name,omitempty"`
	EntryNumber             string `json:"entry_number,omitempty"`
	StartPage               int    `json:"start_page"`
	EndPage                 int    `json:"end_page"`
	MatterType              string `json:"matter_type"`
	ClassificationReasoning string `json:"classification_reasoning,omitempty"`
	ContentType             string `json:"content_type,omitempty"`
	AudioInclude            bool   `json:"audio_include"`
	AudioIncludeReasoning   string `json:"audio_include_reasoning,omitempty"`
	SortOrder               int    `json:"sort_order"`
	WordCount               int    `json:"word_count,omitempty"`
	PageCount               int    `json:"page_count"`
	PolishComplete          bool   `json:"polish_complete"`
	PolishFailed            bool   `json:"polish_failed"`
	PolishedText            string `json:"polished_text,omitempty"`
	EditsAppliedJSON        string `json:"edits_applied_json,omitempty"`
}

// ChapterWithText includes the chapter plus page content.
type ChapterWithText struct {
	Chapter
	Pages      []ChapterPage      `json:"pages,omitempty"`
	Paragraphs []ChapterParagraph `json:"paragraphs,omitempty"`
}

// ChapterPage represents a single page within a chapter.
type ChapterPage struct {
	PageNum     int    `json:"page_num"`
	OcrMarkdown string `json:"ocr_markdown,omitempty"`
}

// ChapterParagraph represents a paragraph within a chapter.
type ChapterParagraph struct {
	ID           string `json:"id"`
	SortOrder    int    `json:"sort_order"`
	StartPage    int    `json:"start_page"`
	RawText      string `json:"raw_text,omitempty"`
	PolishedText string `json:"polished_text,omitempty"`
	WordCount    int    `json:"word_count"`
}

// ChaptersResponse is the response for the chapters endpoint.
type ChaptersResponse struct {
	BookID      string            `json:"book_id"`
	BookTitle   string            `json:"book_title,omitempty"`
	TotalPages  int               `json:"total_pages"`
	Chapters    []ChapterWithText `json:"chapters"`
	HasChapters bool              `json:"has_chapters"`
}

// GetBookChaptersEndpoint handles GET /api/books/{id}/chapters.
type GetBookChaptersEndpoint struct{}

func (e *GetBookChaptersEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{id}/chapters", e.handler
}

func (e *GetBookChaptersEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get book chapters
//	@Description	Get chapter structure with page content
//	@Tags			books
//	@Produce		json
//	@Param			id			path		string	true	"Book ID"
//	@Param			include_text		query		bool	false	"Include page text content"
//	@Param			include_paragraphs	query		bool	false	"Include paragraphs"
//	@Success		200			{object}	ChaptersResponse
//	@Failure		400			{object}	ErrorResponse
//	@Failure		404			{object}	ErrorResponse
//	@Failure		500			{object}	ErrorResponse
//	@Router			/api/books/{id}/chapters [get]
func (e *GetBookChaptersEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book id is required")
		return
	}

	includeText := r.URL.Query().Get("include_text") == "true"
	includeParagraphs := r.URL.Query().Get("include_paragraphs") == "true"

	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	// Get book info
	bookQuery := fmt.Sprintf(`{
		Book(docID: %q) {
			_docID
			title
			page_count
		}
	}`, bookID)

	bookResp, err := client.Query(r.Context(), bookQuery)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	bookData, ok := bookResp.Data["Book"].([]any)
	if !ok || len(bookData) == 0 {
		writeError(w, http.StatusNotFound, "book not found")
		return
	}

	bookMap := bookData[0].(map[string]any)
	bookTitle := getString(bookMap, "title")
	totalPages := 0
	if pc, ok := bookMap["page_count"].(float64); ok {
		totalPages = int(pc)
	}

	// Get chapters
	chapterQuery := fmt.Sprintf(`{
		Chapter(filter: {book: {_docID: {_eq: %q}}}) {
			_docID
			entry_id
			title
			level
			level_name
			entry_number
			start_page
			end_page
			matter_type
			classification_reasoning
			content_type
			audio_include
			audio_include_reasoning
			sort_order
			word_count
			polish_complete
			polish_failed
			polished_text
			edits_applied_json
		}
	}`, bookID)

	chapterResp, err := client.Query(r.Context(), chapterQuery)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	chapterData, _ := chapterResp.Data["Chapter"].([]any)

	chapters := make([]ChapterWithText, 0, len(chapterData))
	for _, c := range chapterData {
		cm, ok := c.(map[string]any)
		if !ok {
			continue
		}

		startPage := getInt(cm, "start_page")
		endPage := getInt(cm, "end_page")

		chapterDocID := getString(cm, "_docID")
		chapter := ChapterWithText{
			Chapter: Chapter{
				ID:                      chapterDocID,
				EntryID:                 getString(cm, "entry_id"),
				Title:                   getString(cm, "title"),
				Level:                   getInt(cm, "level"),
				LevelName:               getString(cm, "level_name"),
				EntryNumber:             getString(cm, "entry_number"),
				StartPage:               startPage,
				EndPage:                 endPage,
				MatterType:              getString(cm, "matter_type"),
				ClassificationReasoning: getString(cm, "classification_reasoning"),
				ContentType:             getString(cm, "content_type"),
				AudioInclude:            getBool(cm, "audio_include"),
				AudioIncludeReasoning:   getString(cm, "audio_include_reasoning"),
				SortOrder:               getInt(cm, "sort_order"),
				WordCount:               getInt(cm, "word_count"),
				PageCount:               endPage - startPage + 1,
				PolishComplete:          getBool(cm, "polish_complete"),
				PolishFailed:            getBool(cm, "polish_failed"),
				PolishedText:            getString(cm, "polished_text"),
				EditsAppliedJSON:        getString(cm, "edits_applied_json"),
			},
		}

		// Fetch page content if requested
		if includeText && startPage > 0 && endPage > 0 {
			pageQuery := fmt.Sprintf(`{
				Page(filter: {
					book_id: {_eq: %q},
					page_num: {_ge: %d, _le: %d}
				}) {
					page_num
					ocr_markdown
				}
			}`, bookID, startPage, endPage)

			pageResp, err := client.Query(r.Context(), pageQuery)
			if err == nil {
				if pageData, ok := pageResp.Data["Page"].([]any); ok {
					for _, p := range pageData {
						pm, ok := p.(map[string]any)
						if !ok {
							continue
						}
						chapter.Pages = append(chapter.Pages, ChapterPage{
							PageNum:     getInt(pm, "page_num"),
							OcrMarkdown: getString(pm, "ocr_markdown"),
						})
					}
					// Sort pages by page number
					sort.Slice(chapter.Pages, func(i, j int) bool {
						return chapter.Pages[i].PageNum < chapter.Pages[j].PageNum
					})
				}
			}
		}

		// Fetch paragraphs if requested
		if includeParagraphs && chapterDocID != "" {
			paraQuery := fmt.Sprintf(`{
				Paragraph(filter: {chapter: {_docID: {_eq: %q}}}, order: {sort_order: ASC}) {
					_docID
					sort_order
					start_page
					raw_text
					polished_text
					word_count
				}
			}`, chapterDocID)

			paraResp, err := client.Query(r.Context(), paraQuery)
			if err == nil {
				if paraData, ok := paraResp.Data["Paragraph"].([]any); ok {
					for _, p := range paraData {
						pm, ok := p.(map[string]any)
						if !ok {
							continue
						}
						chapter.Paragraphs = append(chapter.Paragraphs, ChapterParagraph{
							ID:           getString(pm, "_docID"),
							SortOrder:    getInt(pm, "sort_order"),
							StartPage:    getInt(pm, "start_page"),
							RawText:      getString(pm, "raw_text"),
							PolishedText: getString(pm, "polished_text"),
							WordCount:    getInt(pm, "word_count"),
						})
					}
				}
			}
		}

		chapters = append(chapters, chapter)
	}

	// Sort chapters by sort_order
	sort.Slice(chapters, func(i, j int) bool {
		return chapters[i].SortOrder < chapters[j].SortOrder
	})

	resp := ChaptersResponse{
		BookID:      bookID,
		BookTitle:   bookTitle,
		TotalPages:  totalPages,
		Chapters:    chapters,
		HasChapters: len(chapters) > 0,
	}

	writeJSON(w, http.StatusOK, resp)
}

// getInt extracts an int from a map, returning 0 if not found.
func getInt(m map[string]any, key string) int {
	if v, ok := m[key].(float64); ok {
		return int(v)
	}
	return 0
}

// getBool extracts a bool from a map, returning false if not found.
func getBool(m map[string]any, key string) bool {
	if v, ok := m[key].(bool); ok {
		return v
	}
	return false
}

func (e *GetBookChaptersEndpoint) Command(getServerURL func() string) *cobra.Command {
	var includeText bool
	var includeParagraphs bool

	cmd := &cobra.Command{
		Use:   "chapters <book-id>",
		Short: "Get book chapters",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())

			path := "/api/books/" + args[0] + "/chapters"
			params := []string{}
			if includeText {
				params = append(params, "include_text=true")
			}
			if includeParagraphs {
				params = append(params, "include_paragraphs=true")
			}
			if len(params) > 0 {
				path += "?" + params[0]
				for _, p := range params[1:] {
					path += "&" + p
				}
			}

			var resp ChaptersResponse
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}

	cmd.Flags().BoolVar(&includeText, "include-text", false, "Include page text content")
	cmd.Flags().BoolVar(&includeParagraphs, "include-paragraphs", false, "Include chapter paragraphs")
	return cmd
}
