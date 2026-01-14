package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// joinStrings joins strings with a separator.
func joinStrings(strs []string, sep string) string {
	return strings.Join(strs, sep)
}

// AgentLogSummaryResponse is a brief summary of an agent log.
type AgentLogSummaryResponse struct {
	ID          string `json:"id"`
	AgentType   string `json:"agent_type"`
	BookID      string `json:"book_id"`
	JobID       string `json:"job_id,omitempty"`
	StartedAt   string `json:"started_at"`
	CompletedAt string `json:"completed_at,omitempty"`
	Iterations  int    `json:"iterations"`
	Success     bool   `json:"success"`
	Error       string `json:"error,omitempty"`
}

// AgentLogsListResponse is the response for listing agent logs.
type AgentLogsListResponse struct {
	Logs []AgentLogSummaryResponse `json:"logs"`
}

// ListAgentLogsEndpoint handles GET /api/books/{book_id}/agent-logs.
type ListAgentLogsEndpoint struct{}

func (e *ListAgentLogsEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{book_id}/agent-logs", e.handler
}

func (e *ListAgentLogsEndpoint) RequiresInit() bool { return true }

// stageToAgentTypes maps stage names to agent types.
var stageToAgentTypes = map[string][]string{
	"toc-pattern":        {"pattern_analyzer"},
	"toc-discover":       {"chapter_finder"},
	"toc-validate":       {"gap_investigator"},
	"structure-classify": {"chapter_classifier"},
	"structure-polish":   {"chapter_polisher"},
	"toc":                {"toc_finder", "toc_extract"},
	"toc-link":           {"toc_entry_finder"},
}

// handler godoc
//
//	@Summary		List agent logs for a book
//	@Description	Get all agent execution logs for a book
//	@Tags			agent-logs
//	@Produce		json
//	@Param			book_id		path		string	true	"Book ID"
//	@Param			stage		query		string	false	"Filter by stage (toc-pattern, toc-discover, toc-validate, structure-classify, structure-polish)"
//	@Param			agent_type	query		string	false	"Filter by agent type"
//	@Param			job_id		query		string	false	"Filter by job ID"
//	@Success		200			{object}	AgentLogsListResponse
//	@Failure		400			{object}	ErrorResponse
//	@Failure		500			{object}	ErrorResponse
//	@Failure		503			{object}	ErrorResponse
//	@Router			/api/books/{book_id}/agent-logs [get]
func (e *ListAgentLogsEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	// Validate bookID to prevent GraphQL injection
	if err := defra.ValidateID(bookID); err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid book_id: %v", err))
		return
	}

	// Parse optional filters
	stage := r.URL.Query().Get("stage")
	agentType := r.URL.Query().Get("agent_type")
	jobID := r.URL.Query().Get("job_id")

	// Validate optional filter parameters
	if jobID != "" {
		if err := defra.ValidateID(jobID); err != nil {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid job_id: %v", err))
			return
		}
	}
	if agentType != "" {
		if err := defra.ValidateID(agentType); err != nil {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid agent_type: %v", err))
			return
		}
	}

	defraClient := svcctx.DefraClientFrom(r.Context())
	if defraClient == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	// Build filter
	filters := []string{fmt.Sprintf(`book_id: {_eq: "%s"}`, bookID)}

	if jobID != "" {
		filters = append(filters, fmt.Sprintf(`job_id: {_eq: "%s"}`, jobID))
	}

	// Handle stage -> agent_type mapping
	if stage != "" {
		if agentTypes, ok := stageToAgentTypes[stage]; ok {
			if len(agentTypes) == 1 {
				filters = append(filters, fmt.Sprintf(`agent_type: {_eq: "%s"}`, agentTypes[0]))
			} else {
				// Multiple agent types for this stage
				filters = append(filters, fmt.Sprintf(`agent_type: {_in: ["%s"]}`, joinStrings(agentTypes, `", "`)))
			}
		}
	} else if agentType != "" {
		filters = append(filters, fmt.Sprintf(`agent_type: {_eq: "%s"}`, agentType))
	}

	filterStr := "{" + joinStrings(filters, ", ") + "}"

	query := fmt.Sprintf(`{
		AgentRun(filter: %s) {
			_docID
			agent_type
			book_id
			job_id
			started_at
			completed_at
			iterations
			success
			error
		}
	}`, filterStr)

	queryResp, err := defraClient.Execute(r.Context(), query, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to query agent logs: %v", err))
		return
	}

	resp := AgentLogsListResponse{
		Logs: []AgentLogSummaryResponse{},
	}

	if runs, ok := queryResp.Data["AgentRun"].([]any); ok {
		for _, r := range runs {
			if run, ok := r.(map[string]any); ok {
				log := AgentLogSummaryResponse{}
				if v, ok := run["_docID"].(string); ok {
					log.ID = v
				}
				if v, ok := run["agent_type"].(string); ok {
					log.AgentType = v
				}
				if v, ok := run["book_id"].(string); ok {
					log.BookID = v
				}
				if v, ok := run["job_id"].(string); ok {
					log.JobID = v
				}
				if v, ok := run["started_at"].(string); ok {
					log.StartedAt = v
				}
				if v, ok := run["completed_at"].(string); ok {
					log.CompletedAt = v
				}
				if v, ok := run["iterations"].(float64); ok {
					log.Iterations = int(v)
				}
				if v, ok := run["success"].(bool); ok {
					log.Success = v
				}
				if v, ok := run["error"].(string); ok {
					log.Error = v
				}
				resp.Logs = append(resp.Logs, log)
			}
		}
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *ListAgentLogsEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "agent-logs <book_id>",
		Short: "List agent logs for a book",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			var resp AgentLogsListResponse
			if err := client.Get(ctx, fmt.Sprintf("/api/books/%s/agent-logs", bookID), &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
}

// AgentLogDetailResponse is the full agent log with messages and tool calls.
type AgentLogDetailResponse struct {
	ID          string `json:"id"`
	AgentType   string `json:"agent_type"`
	BookID      string `json:"book_id"`
	JobID       string `json:"job_id,omitempty"`
	StartedAt   string `json:"started_at"`
	CompletedAt string `json:"completed_at,omitempty"`
	Iterations  int    `json:"iterations"`
	Success     bool   `json:"success"`
	Error       string `json:"error,omitempty"`

	// Detailed data
	Messages  json.RawMessage `json:"messages,omitempty"`
	ToolCalls json.RawMessage `json:"tool_calls,omitempty"`
	Result    json.RawMessage `json:"result,omitempty"`
}

// GetAgentLogEndpoint handles GET /api/agent-logs/{id}.
type GetAgentLogEndpoint struct{}

func (e *GetAgentLogEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/agent-logs/{id}", e.handler
}

func (e *GetAgentLogEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get agent log details
//	@Description	Get full agent log including messages and tool calls
//	@Tags			agent-logs
//	@Produce		json
//	@Param			id	path		string	true	"Agent Log ID"
//	@Success		200	{object}	AgentLogDetailResponse
//	@Failure		400	{object}	ErrorResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Failure		503	{object}	ErrorResponse
//	@Router			/api/agent-logs/{id} [get]
func (e *GetAgentLogEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}

	// Validate id to prevent GraphQL injection
	if err := defra.ValidateID(id); err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid id: %v", err))
		return
	}

	defraClient := svcctx.DefraClientFrom(r.Context())
	if defraClient == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	query := fmt.Sprintf(`{
		AgentRun(filter: {_docID: {_eq: "%s"}}) {
			_docID
			agent_type
			book_id
			job_id
			started_at
			completed_at
			iterations
			success
			error
			messages_json
			tool_calls_json
			result_json
		}
	}`, id)

	queryResp, err := defraClient.Execute(r.Context(), query, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to query agent log: %v", err))
		return
	}

	runs, ok := queryResp.Data["AgentRun"].([]any)
	if !ok || len(runs) == 0 {
		writeError(w, http.StatusNotFound, "agent log not found")
		return
	}

	run, ok := runs[0].(map[string]any)
	if !ok {
		writeError(w, http.StatusInternalServerError, "invalid agent log data")
		return
	}

	resp := AgentLogDetailResponse{}
	if v, ok := run["_docID"].(string); ok {
		resp.ID = v
	}
	if v, ok := run["agent_type"].(string); ok {
		resp.AgentType = v
	}
	if v, ok := run["book_id"].(string); ok {
		resp.BookID = v
	}
	if v, ok := run["job_id"].(string); ok {
		resp.JobID = v
	}
	if v, ok := run["started_at"].(string); ok {
		resp.StartedAt = v
	}
	if v, ok := run["completed_at"].(string); ok {
		resp.CompletedAt = v
	}
	if v, ok := run["iterations"].(float64); ok {
		resp.Iterations = int(v)
	}
	if v, ok := run["success"].(bool); ok {
		resp.Success = v
	}
	if v, ok := run["error"].(string); ok {
		resp.Error = v
	}

	// Parse JSON strings into raw JSON for frontend
	if v, ok := run["messages_json"].(string); ok && v != "" {
		resp.Messages = json.RawMessage(v)
	}
	if v, ok := run["tool_calls_json"].(string); ok && v != "" {
		resp.ToolCalls = json.RawMessage(v)
	}
	if v, ok := run["result_json"].(string); ok && v != "" {
		resp.Result = json.RawMessage(v)
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *GetAgentLogEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "agent-log <id>",
		Short: "Get agent log details",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			id := args[0]

			client := api.NewClient(getServerURL())
			var resp AgentLogDetailResponse
			if err := client.Get(ctx, fmt.Sprintf("/api/agent-logs/%s", id), &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
}
