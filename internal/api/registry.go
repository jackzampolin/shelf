package api

import (
	"net/http"

	"github.com/spf13/cobra"
)

// Registry holds all registered endpoints.
type Registry struct {
	endpoints []Endpoint
}

// NewRegistry creates a new endpoint registry.
func NewRegistry() *Registry {
	return &Registry{}
}

// Register adds an endpoint to the registry.
func (r *Registry) Register(ep Endpoint) {
	r.endpoints = append(r.endpoints, ep)
}

// RegisterRoutes registers all endpoint HTTP routes with the given mux.
// initMiddleware wraps handlers that require full server initialization.
func (r *Registry) RegisterRoutes(mux *http.ServeMux, initMiddleware func(http.HandlerFunc) http.HandlerFunc) {
	for _, ep := range r.endpoints {
		method, path, handler := ep.Route()
		if ep.RequiresInit() {
			handler = initMiddleware(handler)
		}
		mux.HandleFunc(method+" "+path, handler)
	}
}

// BuildCommands returns a cobra.Command tree for all registered endpoints.
// Commands are organized by their URL path structure.
// getServerURL is called at runtime to get the server URL.
func (r *Registry) BuildCommands(getServerURL func() string) *cobra.Command {
	apiCmd := &cobra.Command{
		Use:   "api",
		Short: "Commands that call the running server",
		Long: `API commands call the running Shelf server via HTTP.

These commands require a running server (shelf serve).
Use --server to specify a custom server URL.

Examples:
  shelf api health              # Check server health
  shelf api jobs list           # List all jobs
  shelf api jobs get <id>       # Get a specific job`,
	}

	for _, ep := range r.endpoints {
		apiCmd.AddCommand(ep.Command(getServerURL))
	}

	return apiCmd
}

// Endpoints returns all registered endpoints.
func (r *Registry) Endpoints() []Endpoint {
	return r.endpoints
}
