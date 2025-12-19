package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// StartPipelineRequest is the request body for starting a pipeline.
type StartPipelineRequest struct {
	Stage string `json:"stage,omitempty"` // Optional: defaults to "page-processing"
}

// StartPipelineResponse is the response for starting a pipeline.
type StartPipelineResponse struct {
	JobID  string `json:"job_id"`
	Stage  string `json:"stage"`
	BookID string `json:"book_id"`
	Status string `json:"status"`
}

// StartPipelineEndpoint handles POST /api/pipeline/start/{book_id}.
type StartPipelineEndpoint struct{}

func (e *StartPipelineEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/pipeline/start/{book_id}", e.handler
}

func (e *StartPipelineEndpoint) RequiresInit() bool { return true }

func (e *StartPipelineEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	var req StartPipelineRequest
	if r.Body != nil && r.ContentLength > 0 {
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeError(w, http.StatusBadRequest, "invalid request body")
			return
		}
	}

	stageName := req.Stage
	if stageName == "" {
		stageName = "page-processing"
	}

	pipelineRegistry := svcctx.PipelineRegistryFrom(r.Context())
	if pipelineRegistry == nil {
		writeError(w, http.StatusServiceUnavailable, "pipeline registry not initialized")
		return
	}

	stage, ok := pipelineRegistry.Get(stageName)
	if !ok {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("unknown stage: %s", stageName))
		return
	}

	scheduler := svcctx.SchedulerFrom(r.Context())
	if scheduler == nil {
		writeError(w, http.StatusServiceUnavailable, "scheduler not initialized")
		return
	}

	// Create job from stage
	job, err := stage.CreateJob(r.Context(), bookID, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create job: %v", err))
		return
	}

	// Submit to scheduler
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit job: %v", err))
		return
	}

	writeJSON(w, http.StatusAccepted, StartPipelineResponse{
		JobID:  job.ID(),
		Stage:  stageName,
		BookID: bookID,
		Status: "queued",
	})
}

func (e *StartPipelineEndpoint) Command(getServerURL func() string) *cobra.Command {
	var stage string
	cmd := &cobra.Command{
		Use:   "start <book_id>",
		Short: "Start pipeline processing for a book",
		Long: `Start the page processing pipeline for a book.

This processes all pages through OCR, blend, and label stages,
then triggers book-level operations (metadata extraction, ToC finding).

The command submits a job and returns immediately.
Use 'shelf api jobs get <job-id>' to check progress.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			var resp StartPipelineResponse
			if err := client.Post(ctx, "/api/pipeline/start/"+bookID, StartPipelineRequest{
				Stage: stage,
			}, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&stage, "stage", "page-processing", "Pipeline stage to run")
	return cmd
}

// PipelineStatusResponse is the response for pipeline status.
type PipelineStatusResponse struct {
	BookID           string `json:"book_id"`
	Stage            string `json:"stage"`
	TotalPages       int    `json:"total_pages"`
	OcrComplete      int    `json:"ocr_complete"`
	BlendComplete    int    `json:"blend_complete"`
	LabelComplete    int    `json:"label_complete"`
	MetadataComplete bool   `json:"metadata_complete"`
	TocFound         bool   `json:"toc_found"`
	TocExtracted     bool   `json:"toc_extracted"`
	IsComplete       bool   `json:"is_complete"`
}

// PipelineStatusEndpoint handles GET /api/pipeline/status/{book_id}.
type PipelineStatusEndpoint struct{}

func (e *PipelineStatusEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/pipeline/status/{book_id}", e.handler
}

func (e *PipelineStatusEndpoint) RequiresInit() bool { return true }

func (e *PipelineStatusEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	stageName := r.URL.Query().Get("stage")
	if stageName == "" {
		stageName = "page-processing"
	}

	pipelineRegistry := svcctx.PipelineRegistryFrom(r.Context())
	if pipelineRegistry == nil {
		writeError(w, http.StatusServiceUnavailable, "pipeline registry not initialized")
		return
	}

	stage, ok := pipelineRegistry.Get(stageName)
	if !ok {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("unknown stage: %s", stageName))
		return
	}

	status, err := stage.GetStatus(r.Context(), bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to get status: %v", err))
		return
	}

	// Type assert to get the specific status data
	resp := PipelineStatusResponse{
		BookID: bookID,
		Stage:  stageName,
	}

	if data := status.Data(); data != nil {
		// Use type switch to handle the status data
		if statusData, ok := data.(interface {
			TotalPages() int
			OcrComplete() int
			BlendComplete() int
			LabelComplete() int
			MetadataComplete() bool
			TocFound() bool
			TocExtracted() bool
		}); ok {
			resp.TotalPages = statusData.TotalPages()
			resp.OcrComplete = statusData.OcrComplete()
			resp.BlendComplete = statusData.BlendComplete()
			resp.LabelComplete = statusData.LabelComplete()
			resp.MetadataComplete = statusData.MetadataComplete()
			resp.TocFound = statusData.TocFound()
			resp.TocExtracted = statusData.TocExtracted()
		} else if m, ok := data.(map[string]any); ok {
			// Handle map format
			if v, ok := m["total_pages"].(int); ok {
				resp.TotalPages = v
			}
			if v, ok := m["ocr_complete"].(int); ok {
				resp.OcrComplete = v
			}
			if v, ok := m["blend_complete"].(int); ok {
				resp.BlendComplete = v
			}
			if v, ok := m["label_complete"].(int); ok {
				resp.LabelComplete = v
			}
			if v, ok := m["metadata_complete"].(bool); ok {
				resp.MetadataComplete = v
			}
			if v, ok := m["toc_found"].(bool); ok {
				resp.TocFound = v
			}
			if v, ok := m["toc_extracted"].(bool); ok {
				resp.TocExtracted = v
			}
		} else {
			// Try JSON marshaling as last resort
			if b, err := json.Marshal(data); err == nil {
				json.Unmarshal(b, &resp)
			}
		}
	}

	resp.IsComplete = status.IsComplete()
	writeJSON(w, http.StatusOK, resp)
}

func (e *PipelineStatusEndpoint) Command(getServerURL func() string) *cobra.Command {
	var stage string
	cmd := &cobra.Command{
		Use:   "status <book_id>",
		Short: "Get pipeline status for a book",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			path := fmt.Sprintf("/api/pipeline/status/%s", bookID)
			if stage != "page-processing" {
				path += "?stage=" + stage
			}

			client := api.NewClient(getServerURL())
			var resp PipelineStatusResponse
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&stage, "stage", "page-processing", "Pipeline stage to check")
	return cmd
}
