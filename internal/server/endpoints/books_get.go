package endpoints

import (
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// GetBookEndpoint handles GET /api/books/{id}.
type GetBookEndpoint struct{}

func (e *GetBookEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{id}", e.handler
}

func (e *GetBookEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get book by ID
//	@Description	Get detailed information about a book
//	@Tags			books
//	@Produce		json
//	@Param			id	path		string	true	"Book ID"
//	@Success		200	{object}	Book
//	@Failure		400	{object}	ErrorResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Failure		503	{object}	ErrorResponse
//	@Router			/api/books/{id} [get]
func (e *GetBookEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "book id is required")
		return
	}

	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	query := fmt.Sprintf(`{
		Book(docID: %q) {
			_docID
			title
			author
			page_count
			status
			created_at
		}
	}`, id)

	resp, err := client.Query(r.Context(), query)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	if errMsg := resp.Error(); errMsg != "" {
		writeError(w, http.StatusInternalServerError, errMsg)
		return
	}

	data, ok := resp.Data["Book"].([]any)
	if !ok || len(data) == 0 {
		writeError(w, http.StatusNotFound, "book not found")
		return
	}

	m, ok := data[0].(map[string]any)
	if !ok {
		writeError(w, http.StatusInternalServerError, "unexpected response format")
		return
	}

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

	writeJSON(w, http.StatusOK, book)
}

func (e *GetBookEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "get <id>",
		Short: "Get a book by ID",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var book Book
			if err := client.Get(ctx, "/api/books/"+args[0], &book); err != nil {
				return err
			}
			return api.Output(book)
		},
	}
}
