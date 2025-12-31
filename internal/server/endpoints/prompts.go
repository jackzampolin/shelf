package endpoints

import (
	"context"
	"encoding/json"
	"net/http"
	"net/url"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/prompts"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// PromptResponse represents a single prompt.
type PromptResponse struct {
	Key         string   `json:"key"`
	Text        string   `json:"text"`
	Description string   `json:"description,omitempty"`
	Variables   []string `json:"variables,omitempty"`
	Hash        string   `json:"hash,omitempty"`
	DocID       string   `json:"doc_id,omitempty"`
}

// PromptsListResponse contains all prompts.
type PromptsListResponse struct {
	Prompts []PromptResponse `json:"prompts"`
}

// BookPromptResponse represents a resolved prompt for a book.
type BookPromptResponse struct {
	Key        string   `json:"key"`
	Text       string   `json:"text"`
	Variables  []string `json:"variables,omitempty"`
	IsOverride bool     `json:"is_override"`
	CID        string   `json:"cid,omitempty"`
}

// BookPromptsListResponse contains all prompts resolved for a book.
type BookPromptsListResponse struct {
	BookID  string               `json:"book_id"`
	Prompts []BookPromptResponse `json:"prompts"`
}

// SetPromptRequest is the request body for setting a book prompt override.
type SetPromptRequest struct {
	Text string `json:"text"`
	Note string `json:"note,omitempty"`
}

// ListPromptsEndpoint handles GET /api/prompts.
type ListPromptsEndpoint struct{}

func (e *ListPromptsEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/prompts", e.handler
}

func (e *ListPromptsEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		List all prompts
//	@Description	Get all registered prompts with their embedded defaults
//	@Tags			prompts
//	@Produce		json
//	@Success		200	{object}	PromptsListResponse
//	@Failure		500	{object}	ErrorResponse
//	@Router			/api/prompts [get]
func (e *ListPromptsEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	resolver := svcctx.PromptResolverFrom(r.Context())
	if resolver == nil {
		writeError(w, http.StatusInternalServerError, "prompt resolver not available")
		return
	}

	embedded := resolver.AllEmbedded()

	// Sort by key
	sort.Slice(embedded, func(i, j int) bool {
		return embedded[i].Key < embedded[j].Key
	})

	resp := PromptsListResponse{
		Prompts: make([]PromptResponse, len(embedded)),
	}
	for i, p := range embedded {
		resp.Prompts[i] = PromptResponse{
			Key:         p.Key,
			Text:        p.Text,
			Description: p.Description,
			Variables:   p.Variables,
			Hash:        p.Hash,
		}
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *ListPromptsEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List all prompts",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp PromptsListResponse
			if err := client.Get(ctx, "/api/prompts", &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
}

// GetPromptEndpoint handles GET /api/prompts/{key...}.
type GetPromptEndpoint struct{}

func (e *GetPromptEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/prompts/{key...}", e.handler
}

func (e *GetPromptEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get a prompt
//	@Description	Get a specific prompt by key
//	@Tags			prompts
//	@Produce		json
//	@Param			key	path		string	true	"Prompt key (e.g., stages.blend.system)"
//	@Success		200	{object}	PromptResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Router			/api/prompts/{key} [get]
func (e *GetPromptEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	key, err := url.PathUnescape(r.PathValue("key"))
	if err != nil || key == "" {
		writeError(w, http.StatusBadRequest, "invalid prompt key")
		return
	}

	resolver := svcctx.PromptResolverFrom(r.Context())
	if resolver == nil {
		writeError(w, http.StatusInternalServerError, "prompt resolver not available")
		return
	}

	embedded, ok := resolver.GetEmbedded(key)
	if !ok {
		writeError(w, http.StatusNotFound, "prompt not found: "+key)
		return
	}

	writeJSON(w, http.StatusOK, PromptResponse{
		Key:         embedded.Key,
		Text:        embedded.Text,
		Description: embedded.Description,
		Variables:   embedded.Variables,
		Hash:        embedded.Hash,
	})
}

func (e *GetPromptEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "get <key>",
		Short: "Get a prompt by key",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp PromptResponse
			if err := client.Get(ctx, "/api/prompts/"+url.PathEscape(args[0]), &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
}

// ListBookPromptsEndpoint handles GET /api/books/{id}/prompts.
type ListBookPromptsEndpoint struct{}

func (e *ListBookPromptsEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{id}/prompts", e.handler
}

func (e *ListBookPromptsEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		List prompts for a book
//	@Description	Get all prompts resolved for a specific book (with overrides applied)
//	@Tags			prompts
//	@Produce		json
//	@Param			id	path		string	true	"Book ID"
//	@Success		200	{object}	BookPromptsListResponse
//	@Failure		500	{object}	ErrorResponse
//	@Router			/api/books/{id}/prompts [get]
func (e *ListBookPromptsEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book ID required")
		return
	}

	resolver := svcctx.PromptResolverFrom(r.Context())
	if resolver == nil {
		writeError(w, http.StatusInternalServerError, "prompt resolver not available")
		return
	}

	embedded := resolver.AllEmbedded()

	// Sort by key
	sort.Slice(embedded, func(i, j int) bool {
		return embedded[i].Key < embedded[j].Key
	})

	resp := BookPromptsListResponse{
		BookID:  bookID,
		Prompts: make([]BookPromptResponse, 0, len(embedded)),
	}

	for _, p := range embedded {
		resolved, err := resolver.Resolve(r.Context(), p.Key, bookID)
		if err != nil {
			// Skip on error, use embedded
			resp.Prompts = append(resp.Prompts, BookPromptResponse{
				Key:        p.Key,
				Text:       p.Text,
				Variables:  p.Variables,
				IsOverride: false,
			})
			continue
		}
		resp.Prompts = append(resp.Prompts, BookPromptResponse{
			Key:        resolved.Key,
			Text:       resolved.Text,
			Variables:  resolved.Variables,
			IsOverride: resolved.IsOverride,
			CID:        resolved.CID,
		})
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *ListBookPromptsEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "book-list <book-id>",
		Short: "List prompts for a book",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp BookPromptsListResponse
			if err := client.Get(ctx, "/api/books/"+args[0]+"/prompts", &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
}

// GetBookPromptEndpoint handles GET /api/books/{id}/prompts/{key...}.
type GetBookPromptEndpoint struct{}

func (e *GetBookPromptEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{id}/prompts/{key...}", e.handler
}

func (e *GetBookPromptEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get a prompt for a book
//	@Description	Get a specific prompt resolved for a book (with override if exists)
//	@Tags			prompts
//	@Produce		json
//	@Param			id	path		string	true	"Book ID"
//	@Param			key	path		string	true	"Prompt key"
//	@Success		200	{object}	BookPromptResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Router			/api/books/{id}/prompts/{key} [get]
func (e *GetBookPromptEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book ID required")
		return
	}

	key, err := url.PathUnescape(r.PathValue("key"))
	if err != nil || key == "" {
		writeError(w, http.StatusBadRequest, "invalid prompt key")
		return
	}

	resolver := svcctx.PromptResolverFrom(r.Context())
	if resolver == nil {
		writeError(w, http.StatusInternalServerError, "prompt resolver not available")
		return
	}

	resolved, err := resolver.Resolve(r.Context(), key, bookID)
	if err != nil {
		if strings.Contains(err.Error(), "not found") {
			writeError(w, http.StatusNotFound, err.Error())
		} else {
			writeError(w, http.StatusInternalServerError, err.Error())
		}
		return
	}

	writeJSON(w, http.StatusOK, BookPromptResponse{
		Key:        resolved.Key,
		Text:       resolved.Text,
		Variables:  resolved.Variables,
		IsOverride: resolved.IsOverride,
		CID:        resolved.CID,
	})
}

func (e *GetBookPromptEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "book-get <book-id> <key>",
		Short: "Get a prompt for a book",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp BookPromptResponse
			path := "/api/books/" + args[0] + "/prompts/" + url.PathEscape(args[1])
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
}

// SetBookPromptEndpoint handles PUT /api/books/{id}/prompts/{key...}.
type SetBookPromptEndpoint struct{}

func (e *SetBookPromptEndpoint) Route() (string, string, http.HandlerFunc) {
	return "PUT", "/api/books/{id}/prompts/{key...}", e.handler
}

func (e *SetBookPromptEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Set a book prompt override
//	@Description	Set a custom prompt for a specific book
//	@Tags			prompts
//	@Accept			json
//	@Produce		json
//	@Param			id		path		string				true	"Book ID"
//	@Param			key		path		string				true	"Prompt key"
//	@Param			body	body		SetPromptRequest	true	"Prompt override"
//	@Success		200		{object}	BookPromptResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Router			/api/books/{id}/prompts/{key} [put]
func (e *SetBookPromptEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book ID required")
		return
	}

	key, err := url.PathUnescape(r.PathValue("key"))
	if err != nil || key == "" {
		writeError(w, http.StatusBadRequest, "invalid prompt key")
		return
	}

	var req SetPromptRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}

	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	resolver := svcctx.PromptResolverFrom(r.Context())
	if resolver == nil {
		writeError(w, http.StatusInternalServerError, "prompt resolver not available")
		return
	}

	// Verify the key exists
	if _, ok := resolver.GetEmbedded(key); !ok {
		writeError(w, http.StatusNotFound, "prompt key not found: "+key)
		return
	}

	// Get the store from resolver (we need to access it directly)
	// For now, use the store from context
	store := getPromptStore(r.Context())
	if store == nil {
		writeError(w, http.StatusInternalServerError, "prompt store not available")
		return
	}

	if err := store.SetBookOverride(r.Context(), bookID, key, req.Text, req.Note); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to set override: "+err.Error())
		return
	}

	// Return the resolved prompt
	resolved, err := resolver.Resolve(r.Context(), key, bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, BookPromptResponse{
		Key:        resolved.Key,
		Text:       resolved.Text,
		Variables:  resolved.Variables,
		IsOverride: resolved.IsOverride,
		CID:        resolved.CID,
	})
}

func (e *SetBookPromptEndpoint) Command(getServerURL func() string) *cobra.Command {
	var note string
	cmd := &cobra.Command{
		Use:   "book-set <book-id> <key> <text>",
		Short: "Set a book prompt override",
		Args:  cobra.ExactArgs(3),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())

			req := SetPromptRequest{
				Text: args[2],
				Note: note,
			}

			var resp BookPromptResponse
			path := "/api/books/" + args[0] + "/prompts/" + url.PathEscape(args[1])
			if err := client.Put(ctx, path, req, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&note, "note", "", "Note about this override")
	return cmd
}

// ClearBookPromptEndpoint handles DELETE /api/books/{id}/prompts/{key...}.
type ClearBookPromptEndpoint struct{}

func (e *ClearBookPromptEndpoint) Route() (string, string, http.HandlerFunc) {
	return "DELETE", "/api/books/{id}/prompts/{key...}", e.handler
}

func (e *ClearBookPromptEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Clear a book prompt override
//	@Description	Remove a custom prompt override for a book (reverts to default)
//	@Tags			prompts
//	@Produce		json
//	@Param			id	path		string	true	"Book ID"
//	@Param			key	path		string	true	"Prompt key"
//	@Success		200	{object}	BookPromptResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Router			/api/books/{id}/prompts/{key} [delete]
func (e *ClearBookPromptEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book ID required")
		return
	}

	key, err := url.PathUnescape(r.PathValue("key"))
	if err != nil || key == "" {
		writeError(w, http.StatusBadRequest, "invalid prompt key")
		return
	}

	resolver := svcctx.PromptResolverFrom(r.Context())
	if resolver == nil {
		writeError(w, http.StatusInternalServerError, "prompt resolver not available")
		return
	}

	store := getPromptStore(r.Context())
	if store == nil {
		writeError(w, http.StatusInternalServerError, "prompt store not available")
		return
	}

	if err := store.ClearBookOverride(r.Context(), bookID, key); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to clear override: "+err.Error())
		return
	}

	// Return the resolved prompt (now back to default)
	resolved, err := resolver.Resolve(r.Context(), key, bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, BookPromptResponse{
		Key:        resolved.Key,
		Text:       resolved.Text,
		Variables:  resolved.Variables,
		IsOverride: resolved.IsOverride,
		CID:        resolved.CID,
	})
}

func (e *ClearBookPromptEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "book-clear <book-id> <key>",
		Short: "Clear a book prompt override",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			path := "/api/books/" + args[0] + "/prompts/" + url.PathEscape(args[1])
			if err := client.Delete(ctx, path); err != nil {
				return err
			}
			cmd.Println("Override cleared successfully")
			return nil
		},
	}
}

// getPromptStore extracts the prompt store from context.
// This is a helper since we need direct store access for writes.
func getPromptStore(ctx context.Context) *prompts.Store {
	// Get the defra client and create a store
	// This is a workaround since we don't have the store directly in context
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil
	}
	logger := svcctx.LoggerFrom(ctx)
	return prompts.NewStore(defraClient, logger)
}

// PromptsCommands returns endpoints for prompt operations.
func PromptsCommands() []api.Endpoint {
	return []api.Endpoint{
		&ListPromptsEndpoint{},
		&GetPromptEndpoint{},
		&ListBookPromptsEndpoint{},
		&GetBookPromptEndpoint{},
		&SetBookPromptEndpoint{},
		&ClearBookPromptEndpoint{},
	}
}
