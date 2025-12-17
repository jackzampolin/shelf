package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/jackzampolin/shelf/internal/providers"
)

// FileTools provides filesystem operations for agents.
// Useful for testing and for agents that need to read/write files.
type FileTools struct {
	// RootDir constrains all operations to this directory
	RootDir string

	// Result storage
	complete bool
	result   string
}

// NewFileTools creates a FileTools instance constrained to the given directory.
func NewFileTools(rootDir string) *FileTools {
	return &FileTools{
		RootDir: rootDir,
	}
}

// GetTools returns the available filesystem tools.
func (t *FileTools) GetTools() []providers.Tool {
	return []providers.Tool{
		{
			Type: "function",
			Function: providers.ToolFunction{
				Name:        "read_file",
				Description: "Read the contents of a file",
				Parameters: json.RawMessage(`{
					"type": "object",
					"properties": {
						"path": {
							"type": "string",
							"description": "Path to the file (relative to working directory)"
						}
					},
					"required": ["path"]
				}`),
			},
		},
		{
			Type: "function",
			Function: providers.ToolFunction{
				Name:        "write_file",
				Description: "Write content to a file (creates or overwrites)",
				Parameters: json.RawMessage(`{
					"type": "object",
					"properties": {
						"path": {
							"type": "string",
							"description": "Path to the file (relative to working directory)"
						},
						"content": {
							"type": "string",
							"description": "Content to write"
						}
					},
					"required": ["path", "content"]
				}`),
			},
		},
		{
			Type: "function",
			Function: providers.ToolFunction{
				Name:        "list_dir",
				Description: "List files and directories in a path",
				Parameters: json.RawMessage(`{
					"type": "object",
					"properties": {
						"path": {
							"type": "string",
							"description": "Directory path (relative to working directory, use '.' for current)"
						}
					},
					"required": ["path"]
				}`),
			},
		},
		{
			Type: "function",
			Function: providers.ToolFunction{
				Name:        "complete",
				Description: "Signal that the task is complete and provide the final answer",
				Parameters: json.RawMessage(`{
					"type": "object",
					"properties": {
						"result": {
							"type": "string",
							"description": "The final result or answer"
						}
					},
					"required": ["result"]
				}`),
			},
		},
	}
}

// ExecuteTool runs a filesystem tool.
func (t *FileTools) ExecuteTool(ctx context.Context, name string, args map[string]any) (string, error) {
	switch name {
	case "read_file":
		return t.readFile(args)
	case "write_file":
		return t.writeFile(args)
	case "list_dir":
		return t.listDir(args)
	case "complete":
		return t.completeTask(args)
	default:
		return jsonError(fmt.Sprintf("unknown tool: %s", name)), nil
	}
}

// IsComplete returns true when the agent has called the complete tool.
func (t *FileTools) IsComplete() bool {
	return t.complete
}

// GetImages returns nil (no vision support).
func (t *FileTools) GetImages() [][]byte {
	return nil
}

// GetResult returns the result from the complete tool.
func (t *FileTools) GetResult() any {
	return t.result
}

// resolvePath ensures the path is within RootDir.
func (t *FileTools) resolvePath(path string) (string, error) {
	// Clean and resolve the path
	cleaned := filepath.Clean(path)
	if filepath.IsAbs(cleaned) {
		return "", fmt.Errorf("absolute paths not allowed")
	}

	full := filepath.Join(t.RootDir, cleaned)

	// Ensure it's still within RootDir after resolution
	rel, err := filepath.Rel(t.RootDir, full)
	if err != nil {
		return "", fmt.Errorf("invalid path")
	}
	if strings.HasPrefix(rel, "..") {
		return "", fmt.Errorf("path escapes root directory")
	}

	return full, nil
}

func (t *FileTools) readFile(args map[string]any) (string, error) {
	path, ok := args["path"].(string)
	if !ok {
		return jsonError("path is required"), nil
	}

	fullPath, err := t.resolvePath(path)
	if err != nil {
		return jsonError(err.Error()), nil
	}

	content, err := os.ReadFile(fullPath)
	if err != nil {
		return jsonError(fmt.Sprintf("failed to read file: %v", err)), nil
	}

	return jsonResult(map[string]any{
		"content": string(content),
		"path":    path,
	}), nil
}

func (t *FileTools) writeFile(args map[string]any) (string, error) {
	path, ok := args["path"].(string)
	if !ok {
		return jsonError("path is required"), nil
	}
	content, ok := args["content"].(string)
	if !ok {
		return jsonError("content is required"), nil
	}

	fullPath, err := t.resolvePath(path)
	if err != nil {
		return jsonError(err.Error()), nil
	}

	// Create parent directories if needed
	dir := filepath.Dir(fullPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return jsonError(fmt.Sprintf("failed to create directory: %v", err)), nil
	}

	if err := os.WriteFile(fullPath, []byte(content), 0644); err != nil {
		return jsonError(fmt.Sprintf("failed to write file: %v", err)), nil
	}

	return jsonResult(map[string]any{
		"status": "success",
		"path":   path,
		"bytes":  len(content),
	}), nil
}

func (t *FileTools) listDir(args map[string]any) (string, error) {
	path, ok := args["path"].(string)
	if !ok {
		return jsonError("path is required"), nil
	}

	fullPath, err := t.resolvePath(path)
	if err != nil {
		return jsonError(err.Error()), nil
	}

	entries, err := os.ReadDir(fullPath)
	if err != nil {
		return jsonError(fmt.Sprintf("failed to list directory: %v", err)), nil
	}

	var items []map[string]any
	for _, entry := range entries {
		info, _ := entry.Info()
		item := map[string]any{
			"name":  entry.Name(),
			"is_dir": entry.IsDir(),
		}
		if info != nil {
			item["size"] = info.Size()
		}
		items = append(items, item)
	}

	return jsonResult(map[string]any{
		"path":  path,
		"items": items,
	}), nil
}

func (t *FileTools) completeTask(args map[string]any) (string, error) {
	result, ok := args["result"].(string)
	if !ok {
		return jsonError("result is required"), nil
	}

	t.complete = true
	t.result = result

	return jsonResult(map[string]any{
		"status": "completed",
	}), nil
}

// Helper functions for JSON responses
func jsonResult(data map[string]any) string {
	b, _ := json.Marshal(data)
	return string(b)
}

func jsonError(msg string) string {
	b, _ := json.Marshal(map[string]string{"error": msg})
	return string(b)
}
