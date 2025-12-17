package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// HealthResponse is the response for health check endpoints.
type HealthResponse struct {
	Status string `json:"status"`
	Defra  string `json:"defra,omitempty"`
}

// HealthEndpoint handles GET /health.
type HealthEndpoint struct{}

func (e *HealthEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/health", e.handler
}

func (e *HealthEndpoint) RequiresInit() bool { return false }

func (e *HealthEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, HealthResponse{Status: "ok"})
}

func (e *HealthEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "health",
		Short: "Check server health",
		RunE: func(cmd *cobra.Command, args []string) error {
			client := api.NewClient(getServerURL())
			var resp HealthResponse
			if err := client.Get("/health", &resp); err != nil {
				return err
			}
			fmt.Printf("Status: %s\n", resp.Status)
			return nil
		},
	}
}

// ReadyEndpoint handles GET /ready.
type ReadyEndpoint struct{}

func (e *ReadyEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/ready", e.handler
}

func (e *ReadyEndpoint) RequiresInit() bool { return false }

func (e *ReadyEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	resp := HealthResponse{Status: "ok", Defra: "ok"}

	client := svcctx.DefraClientFrom(r.Context())
	if client != nil {
		if err := client.HealthCheck(r.Context()); err != nil {
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

func (e *ReadyEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "ready",
		Short: "Check server readiness (includes DefraDB)",
		RunE: func(cmd *cobra.Command, args []string) error {
			client := api.NewClient(getServerURL())
			var resp HealthResponse
			if err := client.Get("/ready", &resp); err != nil {
				return err
			}
			fmt.Printf("Status: %s\n", resp.Status)
			if resp.Defra != "" {
				fmt.Printf("Defra:  %s\n", resp.Defra)
			}
			return nil
		},
	}
}

// StatusResponse is the detailed status response.
type StatusResponse struct {
	Server    string          `json:"server"`
	Providers ProvidersStatus `json:"providers"`
	Defra     DefraStatus     `json:"defra"`
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

// StatusEndpoint handles GET /status.
type StatusEndpoint struct {
	// DefraManager is set by server since it's not in Services
	DefraManager *defra.DockerManager
}

func (e *StatusEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/status", e.handler
}

func (e *StatusEndpoint) RequiresInit() bool { return false }

func (e *StatusEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	resp := StatusResponse{
		Server: "running",
	}

	// Get registered providers
	registry := svcctx.RegistryFrom(r.Context())
	if registry != nil {
		resp.Providers.OCR = registry.ListOCR()
		resp.Providers.LLM = registry.ListLLM()
	}

	// Get DefraDB container status
	if e.DefraManager != nil {
		status, err := e.DefraManager.Status(r.Context())
		if err != nil {
			resp.Defra.Container = "error"
		} else {
			resp.Defra.Container = string(status)
		}
		resp.Defra.URL = e.DefraManager.URL()
	} else {
		resp.Defra.Container = "not_initialized"
	}

	// Check DefraDB health
	client := svcctx.DefraClientFrom(r.Context())
	if client != nil {
		if err := client.HealthCheck(r.Context()); err != nil {
			resp.Defra.Health = "unhealthy"
		} else {
			resp.Defra.Health = "healthy"
		}
	} else {
		resp.Defra.Health = "not_initialized"
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *StatusEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "status",
		Short: "Get detailed server status",
		RunE: func(cmd *cobra.Command, args []string) error {
			client := api.NewClient(getServerURL())
			var resp StatusResponse
			if err := client.Get("/status", &resp); err != nil {
				return err
			}
			fmt.Printf("Server: %s\n", resp.Server)
			fmt.Printf("Defra:\n")
			fmt.Printf("  Container: %s\n", resp.Defra.Container)
			fmt.Printf("  Health:    %s\n", resp.Defra.Health)
			fmt.Printf("  URL:       %s\n", resp.Defra.URL)
			fmt.Printf("Providers:\n")
			fmt.Printf("  LLM: %v\n", resp.Providers.LLM)
			fmt.Printf("  OCR: %v\n", resp.Providers.OCR)
			return nil
		},
	}
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
