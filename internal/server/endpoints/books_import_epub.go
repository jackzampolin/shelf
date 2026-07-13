package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/epubimport"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ImportEPUBRequest identifies a local EPUB path visible to the Shelf server.
type ImportEPUBRequest struct {
	Path   string `json:"path"`
	Title  string `json:"title,omitempty"`
	Author string `json:"author,omitempty"`
}

// ImportEPUBEndpoint directly materializes structured source text from EPUB.
type ImportEPUBEndpoint struct{}

func (e *ImportEPUBEndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/import/epub", e.handler
}

func (e *ImportEPUBEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Import an EPUB directly
//	@Description	Parse EPUB package/spine text into a terminal structured Shelf book without OCR or LLM processing
//	@Tags			books
//	@Accept			json
//	@Produce		json
//	@Param			request	body		ImportEPUBRequest	true	"EPUB import request"
//	@Success		200		{object}	epubimport.Result
//	@Failure		400		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Failure		503		{object}	ErrorResponse
//	@Router			/api/books/import/epub [post]
func (e *ImportEPUBEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	var req ImportEPUBRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if strings.TrimSpace(req.Path) == "" {
		writeError(w, http.StatusBadRequest, "path is required")
		return
	}
	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}
	homeDir := svcctx.HomeFrom(r.Context())
	if homeDir == nil {
		writeError(w, http.StatusServiceUnavailable, "home directory not initialized")
		return
	}
	result, err := epubimport.Import(r.Context(), client, homeDir, req.Path, epubimport.Options{
		Title: req.Title, Author: req.Author,
	})
	if err != nil {
		status := http.StatusInternalServerError
		if epubimport.IsSourceError(err) {
			status = http.StatusBadRequest
		}
		writeError(w, status, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func (e *ImportEPUBEndpoint) Command(getServerURL func() string) *cobra.Command {
	var title, author string
	cmd := &cobra.Command{
		Use:   "import-epub <epub-file>",
		Short: "Import an EPUB directly as a finished structured book",
		Long: `Parse an EPUB's package, navigation, spine, and source text directly into Shelf.

The command runs to terminal completion and does not invoke scan extraction,
OCR, metadata agents, ToC agents, or chapter polishing. The original EPUB and
its SHA-256 provenance are preserved. Re-importing identical bytes returns the
existing book instead of creating a duplicate.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			filename, err := filepath.Abs(args[0])
			if err != nil {
				return fmt.Errorf("resolve EPUB path: %w", err)
			}
			if !strings.EqualFold(filepath.Ext(filename), ".epub") {
				return fmt.Errorf("source is not an .epub file: %s", filename)
			}
			client := api.NewClient(getServerURL())
			var result epubimport.Result
			if err := client.Post(cmd.Context(), "/api/books/import/epub", ImportEPUBRequest{
				Path: filename, Title: title, Author: author,
			}, &result); err != nil {
				return err
			}
			return api.Output(result)
		},
	}
	cmd.Flags().StringVar(&title, "title", "", "Override EPUB package title")
	cmd.Flags().StringVar(&author, "author", "", "Override EPUB package author")
	return cmd
}
