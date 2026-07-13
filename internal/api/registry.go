package api

import (
	"net/http"
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
