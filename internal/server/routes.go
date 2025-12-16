package server

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/jackzampolin/shelf/internal/jobs"
)

// registerRoutes sets up all HTTP routes.
func (s *Server) registerRoutes(mux *http.ServeMux) {
	// Health endpoints
	mux.HandleFunc("GET /health", s.handleHealth)
	mux.HandleFunc("GET /ready", s.handleReady)
	mux.HandleFunc("GET /status", s.handleStatus)

	// Job endpoints
	mux.HandleFunc("POST /api/jobs", s.handleCreateJob)
	mux.HandleFunc("GET /api/jobs", s.handleListJobs)
	mux.HandleFunc("GET /api/jobs/{id}", s.handleGetJob)
	mux.HandleFunc("PATCH /api/jobs/{id}", s.handleUpdateJob)
}

// HealthResponse is the response for health check endpoints.
type HealthResponse struct {
	Status string `json:"status"`
	Defra  string `json:"defra,omitempty"`
}

// handleHealth returns basic server health.
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	resp := HealthResponse{Status: "ok"}
	writeJSON(w, http.StatusOK, resp)
}

// handleReady returns readiness status including DefraDB health.
func (s *Server) handleReady(w http.ResponseWriter, r *http.Request) {
	resp := HealthResponse{Status: "ok", Defra: "ok"}

	if s.defraClient != nil {
		if err := s.defraClient.HealthCheck(r.Context()); err != nil {
			resp.Status = "degraded"
			resp.Defra = "unhealthy"
			writeJSON(w, http.StatusServiceUnavailable, resp)
			return
		}
	} else {
		resp.Status = "degraded"
		resp.Defra = "not_initialized"
		writeJSON(w, http.StatusServiceUnavailable, resp)
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

// StatusResponse is the detailed status response.
type StatusResponse struct {
	Server    string           `json:"server"`
	Providers ProvidersStatus  `json:"providers"`
	Defra     DefraStatus      `json:"defra"`
}

// ProvidersStatus shows registered OCR and LLM providers.
type ProvidersStatus struct {
	OCR []string `json:"ocr"`
	LLM []string `json:"llm"`
}

// DefraStatus shows DefraDB container and health status.
type DefraStatus struct {
	Container string `json:"container"`
	Health    string `json:"health"`
	URL       string `json:"url"`
}

// handleStatus returns detailed server and DefraDB status.
func (s *Server) handleStatus(w http.ResponseWriter, r *http.Request) {
	resp := StatusResponse{
		Server: "running",
	}

	// Get registered providers
	if s.registry != nil {
		resp.Providers.OCR = s.registry.ListOCR()
		resp.Providers.LLM = s.registry.ListLLM()
	}

	// Get DefraDB container status
	if s.defraManager != nil {
		status, err := s.defraManager.Status(r.Context())
		if err != nil {
			resp.Defra.Container = "error"
		} else {
			resp.Defra.Container = string(status)
		}
		resp.Defra.URL = s.defraManager.URL()
	} else {
		resp.Defra.Container = "not_initialized"
	}

	// Check DefraDB health
	if s.defraClient != nil {
		if err := s.defraClient.HealthCheck(r.Context()); err != nil {
			resp.Defra.Health = "unhealthy"
		} else {
			resp.Defra.Health = "healthy"
		}
	} else {
		resp.Defra.Health = "not_initialized"
	}

	writeJSON(w, http.StatusOK, resp)
}

// CreateJobRequest is the request body for creating a job.
type CreateJobRequest struct {
	JobType  string         `json:"job_type"`
	Metadata map[string]any `json:"metadata,omitempty"`
}

// CreateJobResponse is the response for creating a job.
type CreateJobResponse struct {
	ID string `json:"id"`
}

// handleCreateJob creates a new job.
func (s *Server) handleCreateJob(w http.ResponseWriter, r *http.Request) {
	if s.jobManager == nil {
		writeError(w, http.StatusServiceUnavailable, "job manager not initialized")
		return
	}

	var req CreateJobRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	if req.JobType == "" {
		writeError(w, http.StatusBadRequest, "job_type is required")
		return
	}

	id, err := s.jobManager.Create(r.Context(), req.JobType, req.Metadata)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusCreated, CreateJobResponse{ID: id})
}

// handleGetJob returns a job by ID.
func (s *Server) handleGetJob(w http.ResponseWriter, r *http.Request) {
	if s.jobManager == nil {
		writeError(w, http.StatusServiceUnavailable, "job manager not initialized")
		return
	}

	id := r.PathValue("id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "job id is required")
		return
	}

	job, err := s.jobManager.Get(r.Context(), id)
	if err != nil {
		if strings.Contains(err.Error(), "not found") {
			writeError(w, http.StatusNotFound, "job not found")
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, job)
}

// ListJobsResponse is the response for listing jobs.
type ListJobsResponse struct {
	Jobs []*jobs.Record `json:"jobs"`
}

// handleListJobs returns jobs matching optional filters.
func (s *Server) handleListJobs(w http.ResponseWriter, r *http.Request) {
	if s.jobManager == nil {
		writeError(w, http.StatusServiceUnavailable, "job manager not initialized")
		return
	}

	filter := jobs.ListFilter{
		Status:  jobs.Status(r.URL.Query().Get("status")),
		JobType: r.URL.Query().Get("job_type"),
	}

	jobsList, err := s.jobManager.List(r.Context(), filter)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, ListJobsResponse{Jobs: jobsList})
}

// UpdateJobRequest is the request body for updating a job.
type UpdateJobRequest struct {
	Status   string         `json:"status,omitempty"`
	Error    string         `json:"error,omitempty"`
	Metadata map[string]any `json:"metadata,omitempty"`
}

// handleUpdateJob updates a job's status or metadata.
func (s *Server) handleUpdateJob(w http.ResponseWriter, r *http.Request) {
	if s.jobManager == nil {
		writeError(w, http.StatusServiceUnavailable, "job manager not initialized")
		return
	}

	id := r.PathValue("id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "job id is required")
		return
	}

	var req UpdateJobRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	// Update status if provided
	if req.Status != "" {
		if err := s.jobManager.UpdateStatus(r.Context(), id, jobs.Status(req.Status), req.Error); err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}
	}

	// Update metadata if provided
	if req.Metadata != nil {
		if err := s.jobManager.UpdateMetadata(r.Context(), id, req.Metadata); err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}
	}

	// Return updated job
	job, err := s.jobManager.Get(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, job)
}

// writeJSON writes a JSON response.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

// ErrorResponse is a standard error response.
type ErrorResponse struct {
	Error string `json:"error"`
}

// writeError writes a JSON error response.
func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, ErrorResponse{Error: msg})
}
