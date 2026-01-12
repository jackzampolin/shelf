package endpoints

import (
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ListBooksResponse is the response for listing books.
type ListBooksResponse struct {
	Books []Book `json:"books"`
}

// Book represents a book record.
type Book struct {
	ID                    string `json:"id"`
	Title                 string `json:"title"`
	Author                string `json:"author,omitempty"`
	PageCount             int    `json:"page_count"`
	Status                string `json:"status"`
	CreatedAt             string `json:"created_at"`
	PatternAnalysisJSON   string `json:"page_pattern_analysis_json,omitempty"`
}

// ListBooksEndpoint handles GET /api/books.
type ListBooksEndpoint struct{}

func (e *ListBooksEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books", e.handler
}

func (e *ListBooksEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		List books
//	@Description	List all books in the library
//	@Tags			books
//	@Produce		json
//	@Success		200	{object}	ListBooksResponse
//	@Failure		500	{object}	ErrorResponse
//	@Failure		503	{object}	ErrorResponse
//	@Router			/api/books [get]
func (e *ListBooksEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	resp, err := client.Query(r.Context(), `{
		Book {
			_docID
			title
			author
			page_count
			status
			created_at
		}
	}`)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	if errMsg := resp.Error(); errMsg != "" {
		writeError(w, http.StatusInternalServerError, errMsg)
		return
	}

	var books []Book
	if data, ok := resp.Data["Book"].([]any); ok {
		for _, item := range data {
			if m, ok := item.(map[string]any); ok {
				book := Book{
					ID:     getString(m, "_docID"),
					Title:  getString(m, "title"),
					Author: getString(m, "author"),
					Status: getString(m, "status"),
				}
				if pc, ok := m["page_count"].(float64); ok {
					book.PageCount = int(pc)
				}
				if ca, ok := m["created_at"].(string); ok {
					book.CreatedAt = ca
				}
				books = append(books, book)
			}
		}
	}

	writeJSON(w, http.StatusOK, ListBooksResponse{Books: books})
}

func (e *ListBooksEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List all books",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp ListBooksResponse
			if err := client.Get(ctx, "/api/books", &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
}

// getString safely extracts a string from a map.
func getString(m map[string]any, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}
