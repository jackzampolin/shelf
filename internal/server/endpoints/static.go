package endpoints

import (
	"io/fs"
	"net/http"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/web"
)

// StaticEndpoint serves the embedded frontend assets.
// It handles SPA routing by serving index.html for unknown paths.
type StaticEndpoint struct{}

var _ api.Endpoint = (*StaticEndpoint)(nil)

func (e *StaticEndpoint) Route() (string, string, http.HandlerFunc) {
	// Use Go 1.22 wildcard pattern to catch all unmatched GET requests
	return "GET", "/{path...}", e.handler
}

func (e *StaticEndpoint) RequiresInit() bool {
	return false
}

func (e *StaticEndpoint) Command(_ func() string) *cobra.Command {
	return nil // No CLI command for static files
}

func (e *StaticEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	// Get the embedded filesystem
	distFS, err := web.DistFS()
	if err != nil {
		http.Error(w, "Frontend not available", http.StatusInternalServerError)
		return
	}

	path := r.URL.Path

	// Determine file path to serve
	filePath := strings.TrimPrefix(path, "/")
	if filePath == "" {
		filePath = "index.html"
	}

	// Check if file exists in embedded FS
	file, err := distFS.Open(filePath)
	if err == nil {
		file.Close()
		// File exists - serve it
		http.FileServer(http.FS(distFS)).ServeHTTP(w, r)
		return
	}

	// File doesn't exist - serve index.html for SPA routing
	// This allows frontend routes like /books, /jobs to work
	indexFile, err := fs.ReadFile(distFS, "index.html")
	if err != nil {
		http.Error(w, "Frontend not available", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write(indexFile)
}
