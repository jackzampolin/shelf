package endpoints

import (
	"fmt"
	"net/http"
	"os"
	"strconv"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// PageImageEndpoint handles GET /api/books/{book_id}/pages/{page_num}/image.
type PageImageEndpoint struct{}

var _ api.Endpoint = (*PageImageEndpoint)(nil)

func (e *PageImageEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{book_id}/pages/{page_num}/image", e.handler
}

func (e *PageImageEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get page image
//	@Description	Get the PNG image for a specific page of a book
//	@Tags			pages
//	@Produce		image/png
//	@Param			book_id		path		string	true	"Book ID"
//	@Param			page_num	path		int		true	"Page number (1-indexed)"
//	@Success		200			{file}		binary
//	@Failure		400			{object}	ErrorResponse
//	@Failure		404			{object}	ErrorResponse
//	@Failure		503			{object}	ErrorResponse
//	@Router			/api/books/{book_id}/pages/{page_num}/image [get]
func (e *PageImageEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	pageNumStr := r.PathValue("page_num")
	pageNum, err := strconv.Atoi(pageNumStr)
	if err != nil || pageNum < 1 {
		writeError(w, http.StatusBadRequest, "page_num must be a positive integer")
		return
	}

	homeDir := svcctx.HomeFrom(r.Context())
	if homeDir == nil {
		writeError(w, http.StatusServiceUnavailable, "home directory not initialized")
		return
	}

	imagePath := homeDir.SourceImagePath(bookID, pageNum)

	file, err := os.Open(imagePath)
	if err != nil {
		if os.IsNotExist(err) {
			writeError(w, http.StatusNotFound, fmt.Sprintf("page %d not found", pageNum))
		} else {
			writeError(w, http.StatusInternalServerError, err.Error())
		}
		return
	}
	defer file.Close()

	fileInfo, err := file.Stat()
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	w.Header().Set("Content-Type", "image/png")
	w.Header().Set("Cache-Control", "public, max-age=31536000")
	http.ServeContent(w, r, fmt.Sprintf("page_%04d.png", pageNum), fileInfo.ModTime(), file)
}

func (e *PageImageEndpoint) Command(_ func() string) *cobra.Command {
	return nil
}

// ListPagesResponse is the response for listing pages.
type ListPagesResponse struct {
	Pages      []PageSummary `json:"pages"`
	TotalPages int           `json:"total_pages"`
}

// PageSummary is a brief summary of a page.
type PageSummary struct {
	PageNum     int  `json:"page_num"`
	OcrComplete bool `json:"ocr_complete"`
}

// ListPagesEndpoint handles GET /api/books/{book_id}/pages.
type ListPagesEndpoint struct{}

var _ api.Endpoint = (*ListPagesEndpoint)(nil)

func (e *ListPagesEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{book_id}/pages", e.handler
}

func (e *ListPagesEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		List pages
//	@Description	List all pages for a book with processing status
//	@Tags			pages
//	@Produce		json
//	@Param			book_id	path		string	true	"Book ID"
//	@Success		200		{object}	ListPagesResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Failure		503		{object}	ErrorResponse
//	@Router			/api/books/{book_id}/pages [get]
func (e *ListPagesEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	// Query pages for this book
	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}, order: {page_num: ASC}) {
			page_num
			ocr_complete
		}
	}`, bookID)

	resp, err := client.Query(r.Context(), query)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	if errMsg := resp.Error(); errMsg != "" {
		writeError(w, http.StatusInternalServerError, errMsg)
		return
	}

	var pages []PageSummary
	if data, ok := resp.Data["Page"].([]any); ok {
		for _, item := range data {
			if m, ok := item.(map[string]any); ok {
				page := PageSummary{}
				if pn, ok := m["page_num"].(float64); ok {
					page.PageNum = int(pn)
				}
				if oc, ok := m["ocr_complete"].(bool); ok {
					page.OcrComplete = oc
				}
				pages = append(pages, page)
			}
		}
	}

	writeJSON(w, http.StatusOK, ListPagesResponse{
		Pages:      pages,
		TotalPages: len(pages),
	})
}

func (e *ListPagesEndpoint) Command(_ func() string) *cobra.Command {
	return nil
}

// PageStatus contains processing status flags.
type PageStatus struct {
	ExtractComplete bool `json:"extract_complete"`
	OcrComplete     bool `json:"ocr_complete"`
}

// OcrResult represents a single OCR provider's output.
type OcrResult struct {
	Provider   string  `json:"provider"`
	Text       string  `json:"text"`
	Confidence float64 `json:"confidence"`
}

// GetPageResponse is the response for getting a single page.
type GetPageResponse struct {
	PageNum     int         `json:"page_num"`
	OcrMarkdown string      `json:"ocr_markdown"`
	OcrResults  []OcrResult `json:"ocr_results"`
	Status      PageStatus  `json:"status"`
}

// GetPageEndpoint handles GET /api/books/{book_id}/pages/{page_num}.
type GetPageEndpoint struct{}

var _ api.Endpoint = (*GetPageEndpoint)(nil)

func (e *GetPageEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{book_id}/pages/{page_num}", e.handler
}

func (e *GetPageEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get page details
//	@Description	Get full details for a specific page including OCR results
//	@Tags			pages
//	@Produce		json
//	@Param			book_id		path		string	true	"Book ID"
//	@Param			page_num	path		int		true	"Page number (1-indexed)"
//	@Success		200			{object}	GetPageResponse
//	@Failure		400			{object}	ErrorResponse
//	@Failure		404			{object}	ErrorResponse
//	@Failure		500			{object}	ErrorResponse
//	@Failure		503			{object}	ErrorResponse
//	@Router			/api/books/{book_id}/pages/{page_num} [get]
func (e *GetPageEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	pageNumStr := r.PathValue("page_num")
	pageNum, err := strconv.Atoi(pageNumStr)
	if err != nil || pageNum < 1 {
		writeError(w, http.StatusBadRequest, "page_num must be a positive integer")
		return
	}

	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	// Query page with OCR results
	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, page_num: {_eq: %d}}) {
			page_num
			ocr_markdown
			extract_complete
			ocr_complete
			ocr_results {
				provider
				text
				confidence
			}
		}
	}`, bookID, pageNum)

	resp, err := client.Query(r.Context(), query)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	if errMsg := resp.Error(); errMsg != "" {
		writeError(w, http.StatusInternalServerError, errMsg)
		return
	}

	data, ok := resp.Data["Page"].([]any)
	if !ok || len(data) == 0 {
		writeError(w, http.StatusNotFound, "page not found")
		return
	}

	m, ok := data[0].(map[string]any)
	if !ok {
		writeError(w, http.StatusInternalServerError, "unexpected response format")
		return
	}

	response := GetPageResponse{
		Status: PageStatus{},
	}

	if pn, ok := m["page_num"].(float64); ok {
		response.PageNum = int(pn)
	}
	if om, ok := m["ocr_markdown"].(string); ok {
		response.OcrMarkdown = om
	}

	// Status
	if ec, ok := m["extract_complete"].(bool); ok {
		response.Status.ExtractComplete = ec
	}
	if oc, ok := m["ocr_complete"].(bool); ok {
		response.Status.OcrComplete = oc
	}

	// OCR Results
	if ocrResults, ok := m["ocr_results"].([]any); ok {
		for _, or := range ocrResults {
			if orm, ok := or.(map[string]any); ok {
				result := OcrResult{}
				if p, ok := orm["provider"].(string); ok {
					result.Provider = p
				}
				if t, ok := orm["text"].(string); ok {
					result.Text = t
				}
				if c, ok := orm["confidence"].(float64); ok {
					result.Confidence = c
				}
				response.OcrResults = append(response.OcrResults, result)
			}
		}
	}

	writeJSON(w, http.StatusOK, response)
}

func (e *GetPageEndpoint) Command(_ func() string) *cobra.Command {
	return nil
}
