package api

import (
	"net/http"

	"github.com/spf13/cobra"
)

// Endpoint defines both an HTTP route and its corresponding CLI command.
// This provides a single source of truth for API operations.
type Endpoint interface {
	// Route returns the HTTP method, path, and handler for this endpoint.
	Route() (method, path string, handler http.HandlerFunc)

	// RequiresInit returns true if this endpoint requires the server
	// to be fully initialized (DefraDB + job manager ready).
	RequiresInit() bool

	// Command returns a Cobra command that calls this endpoint via HTTP.
	// getServerURL is called at runtime to get the server URL (deferred evaluation).
	Command(getServerURL func() string) *cobra.Command
}
