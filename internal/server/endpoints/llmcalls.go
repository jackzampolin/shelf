package endpoints

import (
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/llmcall"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// LLMCallsResponse contains a list of LLM calls.
type LLMCallsResponse struct {
	Calls []llmcall.Call `json:"calls"`
	Total int            `json:"total"`
}

// LLMCallResponse contains a single LLM call.
type LLMCallResponse struct {
	Call  *llmcall.Call `json:"call,omitempty"`
	Error string        `json:"error,omitempty"`
}

// LLMCallCountsResponse contains prompt key counts.
type LLMCallCountsResponse struct {
	Counts map[string]int `json:"counts"`
}

// ListLLMCallsEndpoint handles GET /api/llmcalls.
type ListLLMCallsEndpoint struct{}

func (e *ListLLMCallsEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/llmcalls", e.handler
}

func (e *ListLLMCallsEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		List LLM calls
//	@Description	Get LLM call history with optional filters
//	@Tags			llmcalls
//	@Produce		json
//	@Param			book_id		query		string	false	"Filter by book ID"
//	@Param			page_id		query		string	false	"Filter by page ID"
//	@Param			job_id		query		string	false	"Filter by job ID"
//	@Param			prompt_key	query		string	false	"Filter by prompt key"
//	@Param			provider	query		string	false	"Filter by provider"
//	@Param			model		query		string	false	"Filter by model"
//	@Param			success		query		bool	false	"Filter by success status (true or false)"
//	@Param			limit		query		int		false	"Max results (default 100)"
//	@Param			offset		query		int		false	"Result offset"
//	@Param			after		query		string	false	"Filter calls after this RFC3339 timestamp"
//	@Param			before		query		string	false	"Filter calls before this RFC3339 timestamp"
//	@Success		200			{object}	LLMCallsResponse
//	@Failure		400			{object}	ErrorResponse
//	@Failure		500			{object}	ErrorResponse
//	@Router			/api/llmcalls [get]
func (e *ListLLMCallsEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	store := svcctx.LLMCallStoreFrom(r.Context())
	if store == nil {
		writeError(w, http.StatusInternalServerError, "LLM call store not available")
		return
	}

	q := r.URL.Query()
	filter := llmcall.QueryFilter{
		BookID:    q.Get("book_id"),
		PageID:    q.Get("page_id"),
		JobID:     q.Get("job_id"),
		PromptKey: q.Get("prompt_key"),
		Provider:  q.Get("provider"),
		Model:     q.Get("model"),
	}

	if v := q.Get("success"); v != "" {
		b, err := strconv.ParseBool(v)
		if err != nil {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid success filter: %q must be true or false", v))
			return
		}
		filter.Success = &b
	}

	if v := q.Get("limit"); v != "" {
		limit, err := strconv.Atoi(v)
		if err != nil {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid limit: %q must be an integer", v))
			return
		}
		filter.Limit = limit
	}
	if filter.Limit <= 0 {
		filter.Limit = 100
	}

	if v := q.Get("offset"); v != "" {
		offset, err := strconv.Atoi(v)
		if err != nil {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid offset: %q must be an integer", v))
			return
		}
		filter.Offset = offset
	}

	if v := q.Get("after"); v != "" {
		t, err := time.Parse(time.RFC3339, v)
		if err != nil {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid after time: %q must be RFC3339 format (e.g., 2024-01-15T00:00:00Z)", v))
			return
		}
		filter.After = &t
	}
	if v := q.Get("before"); v != "" {
		t, err := time.Parse(time.RFC3339, v)
		if err != nil {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid before time: %q must be RFC3339 format (e.g., 2024-01-15T00:00:00Z)", v))
			return
		}
		filter.Before = &t
	}

	calls, err := store.List(r.Context(), filter)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, LLMCallsResponse{
		Calls: calls,
		Total: len(calls),
	})
}

func (e *ListLLMCallsEndpoint) Command(getServerURL func() string) *cobra.Command {
	var bookID, pageID, jobID, promptKey, provider, model string
	var limit, offset int
	var successOnly, failedOnly bool

	cmd := &cobra.Command{
		Use:   "list",
		Short: "List LLM calls",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())

			// Build query params
			params := url.Values{}
			if bookID != "" {
				params.Set("book_id", bookID)
			}
			if pageID != "" {
				params.Set("page_id", pageID)
			}
			if jobID != "" {
				params.Set("job_id", jobID)
			}
			if promptKey != "" {
				params.Set("prompt_key", promptKey)
			}
			if provider != "" {
				params.Set("provider", provider)
			}
			if model != "" {
				params.Set("model", model)
			}
			if successOnly {
				params.Set("success", "true")
			}
			if failedOnly {
				params.Set("success", "false")
			}
			if limit > 0 {
				params.Set("limit", strconv.Itoa(limit))
			}
			if offset > 0 {
				params.Set("offset", strconv.Itoa(offset))
			}

			path := "/api/llmcalls"
			if len(params) > 0 {
				path += "?" + params.Encode()
			}

			var resp LLMCallsResponse
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&bookID, "book-id", "", "Filter by book ID")
	cmd.Flags().StringVar(&pageID, "page-id", "", "Filter by page ID")
	cmd.Flags().StringVar(&jobID, "job-id", "", "Filter by job ID")
	cmd.Flags().StringVar(&promptKey, "prompt-key", "", "Filter by prompt key")
	cmd.Flags().StringVar(&provider, "provider", "", "Filter by provider")
	cmd.Flags().StringVar(&model, "model", "", "Filter by model")
	cmd.Flags().BoolVar(&successOnly, "success", false, "Only show successful calls")
	cmd.Flags().BoolVar(&failedOnly, "failed", false, "Only show failed calls")
	cmd.Flags().IntVar(&limit, "limit", 100, "Max results")
	cmd.Flags().IntVar(&offset, "offset", 0, "Result offset")
	return cmd
}

// GetLLMCallEndpoint handles GET /api/llmcalls/{id}.
type GetLLMCallEndpoint struct{}

func (e *GetLLMCallEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/llmcalls/{id}", e.handler
}

func (e *GetLLMCallEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get an LLM call
//	@Description	Get a single LLM call by ID
//	@Tags			llmcalls
//	@Produce		json
//	@Param			id	path		string	true	"LLM call ID"
//	@Success		200	{object}	LLMCallResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Router			/api/llmcalls/{id} [get]
func (e *GetLLMCallEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "id required")
		return
	}

	store := svcctx.LLMCallStoreFrom(r.Context())
	if store == nil {
		writeError(w, http.StatusInternalServerError, "LLM call store not available")
		return
	}

	call, err := store.Get(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if call == nil {
		writeError(w, http.StatusNotFound, "LLM call not found")
		return
	}

	writeJSON(w, http.StatusOK, LLMCallResponse{Call: call})
}

func (e *GetLLMCallEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "get <id>",
		Short: "Get an LLM call by ID",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			id := args[0]
			client := api.NewClient(getServerURL())
			var resp LLMCallResponse
			if err := client.Get(ctx, "/api/llmcalls/"+id, &resp); err != nil {
				return err
			}
			return api.Output(resp.Call)
		},
	}
}

// LLMCallCountsEndpoint handles GET /api/llmcalls/counts/{book_id}.
type LLMCallCountsEndpoint struct{}

func (e *LLMCallCountsEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/llmcalls/counts/{book_id}", e.handler
}

func (e *LLMCallCountsEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get LLM call counts by prompt key
//	@Description	Get count of LLM calls grouped by prompt key for a book
//	@Tags			llmcalls
//	@Produce		json
//	@Param			book_id	path		string	true	"Book ID"
//	@Success		200		{object}	LLMCallCountsResponse
//	@Failure		500		{object}	ErrorResponse
//	@Router			/api/llmcalls/counts/{book_id} [get]
func (e *LLMCallCountsEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id required")
		return
	}

	store := svcctx.LLMCallStoreFrom(r.Context())
	if store == nil {
		writeError(w, http.StatusInternalServerError, "LLM call store not available")
		return
	}

	counts, err := store.CountByPromptKey(r.Context(), bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, LLMCallCountsResponse{Counts: counts})
}

func (e *LLMCallCountsEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "counts <book-id>",
		Short: "Get LLM call counts by prompt key for a book",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]
			client := api.NewClient(getServerURL())
			var resp LLMCallCountsResponse
			if err := client.Get(ctx, "/api/llmcalls/counts/"+bookID, &resp); err != nil {
				return err
			}
			return api.Output(resp.Counts)
		},
	}
}
