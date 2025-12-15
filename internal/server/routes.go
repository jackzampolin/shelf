package server

import (
	"encoding/json"
	"net/http"
)

// registerRoutes sets up all HTTP routes.
func (s *Server) registerRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /health", s.handleHealth)
	mux.HandleFunc("GET /ready", s.handleReady)
}

// HealthResponse is the response for health check endpoints.
type HealthResponse struct {
	Status string `json:"status"`
	Defra  string `json:"defra,omitempty"`
}

// handleHealth returns basic server health.
// This returns OK if the HTTP server is responding.
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	resp := HealthResponse{Status: "ok"}
	writeJSON(w, http.StatusOK, resp)
}

// handleReady returns readiness status including DefraDB health.
// This returns OK only if both the server AND DefraDB are healthy.
func (s *Server) handleReady(w http.ResponseWriter, r *http.Request) {
	resp := HealthResponse{Status: "ok", Defra: "ok"}

	// Check DefraDB health
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

// writeJSON writes a JSON response.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}
