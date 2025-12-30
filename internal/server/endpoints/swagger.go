package endpoints

import (
	"net/http"
	"os"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
)

// SwaggerEndpoint serves the OpenAPI spec.
type SwaggerEndpoint struct {
	// SpecPath is the path to the swagger.json file
	SpecPath string
}

func (e *SwaggerEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/swagger.json", e.handler
}

func (e *SwaggerEndpoint) RequiresInit() bool { return false }

func (e *SwaggerEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	specPath := e.SpecPath
	if specPath == "" {
		// Default to docs/swagger/swagger.json relative to working dir
		specPath = "docs/swagger/swagger.json"
	}

	data, err := os.ReadFile(specPath)
	if err != nil {
		writeError(w, http.StatusNotFound, "swagger.json not found")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Write(data)
}

func (e *SwaggerEndpoint) Command(getServerURL func() string) *cobra.Command {
	var outputFile string
	cmd := &cobra.Command{
		Use:   "swagger",
		Short: "Fetch OpenAPI spec from server",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())

			var spec map[string]any
			if err := client.Get(ctx, "/swagger.json", &spec); err != nil {
				return err
			}

			if outputFile != "" {
				return api.OutputToFile(spec, outputFile)
			}
			return api.Output(spec)
		},
	}
	cmd.Flags().StringVarP(&outputFile, "output", "o", "", "Output file path")
	return cmd
}

// SwaggerUIEndpoint serves Swagger UI.
type SwaggerUIEndpoint struct{}

func (e *SwaggerUIEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/swagger", e.handler
}

func (e *SwaggerUIEndpoint) RequiresInit() bool { return false }

func (e *SwaggerUIEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	html := `<!DOCTYPE html>
<html>
<head>
  <title>Shelf API</title>
  <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: '/swagger.json',
      dom_id: '#swagger-ui',
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: 'BaseLayout'
    });
  </script>
</body>
</html>`
	w.Header().Set("Content-Type", "text/html")
	w.Write([]byte(html))
}

func (e *SwaggerUIEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:    "swagger-ui",
		Hidden: true,
		Short:  "Open Swagger UI in browser",
		RunE: func(cmd *cobra.Command, args []string) error {
			cmd.Println("Open in browser:", getServerURL()+"/swagger")
			return nil
		},
	}
}

// GetSwaggerSpecPath returns the path to swagger.json based on executable location.
func GetSwaggerSpecPath() string {
	// Try relative to executable first
	if exe, err := os.Executable(); err == nil {
		specPath := filepath.Join(filepath.Dir(exe), "docs", "swagger", "swagger.json")
		if _, err := os.Stat(specPath); err == nil {
			return specPath
		}
	}
	// Fall back to working directory
	return "docs/swagger/swagger.json"
}
