package testutil

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"testing"
	"time"
)

// DefraTestConfig holds DefraDB container configuration without importing defra package.
// This breaks the import cycle between testutil and defra.
type DefraTestConfig struct {
	ContainerName string
	HostPort      string
	Labels        map[string]string
}

// ServerConfig returns configuration values for creating a test server.
// This avoids importing the server package directly.
type ServerConfig struct {
	Host          string
	Port          string
	DefraDataPath string
	ConfigFile    string
	DefraConfig   DefraTestConfig
	Logger        *slog.Logger
}

// NewServerConfig creates configuration for a test server with unique ports.
func NewServerConfig(t *testing.T) ServerConfig {
	t.Helper()

	// Register Docker cleanup for this test
	_ = DockerClient(t)

	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo}))
	tempDir := t.TempDir()

	// Find free ports for HTTP server and DefraDB
	httpPort, err := FindFreePort()
	if err != nil {
		t.Fatalf("failed to find free port for HTTP: %v", err)
	}
	defraPort, err := FindFreePort()
	if err != nil {
		t.Fatalf("failed to find free port for DefraDB: %v", err)
	}

	containerName := UniqueContainerName(t, "defra")
	configFile := tempDir + "/config.yaml"

	return ServerConfig{
		Host:          "127.0.0.1",
		Port:          httpPort,
		DefraDataPath: tempDir,
		ConfigFile:    configFile,
		DefraConfig: DefraTestConfig{
			ContainerName: containerName,
			HostPort:      defraPort,
			Labels:        ContainerLabels(t),
		},
		Logger: logger,
	}
}

// URL returns the server URL for the given config.
func (c ServerConfig) URL() string {
	return fmt.Sprintf("http://%s:%s", c.Host, c.Port)
}

// WaitForServer polls the /api/status endpoint until DefraDB is healthy.
func WaitForServer(url string, timeout time.Duration) error {
	client := &http.Client{Timeout: 2 * time.Second}
	deadline := time.Now().Add(timeout)

	for time.Now().Before(deadline) {
		resp, err := client.Get(url + "/api/status")
		if err == nil {
			var status struct {
				Defra struct {
					Health string `json:"health"`
				} `json:"defra"`
			}
			if err := json.NewDecoder(resp.Body).Decode(&status); err == nil {
				if status.Defra.Health == "healthy" {
					resp.Body.Close()
					return nil
				}
			}
			resp.Body.Close()
		}
		time.Sleep(500 * time.Millisecond)
	}

	return fmt.Errorf("server not ready after %v", timeout)
}

// FindFreePort finds an available TCP port and returns it as a string.
func FindFreePort() (string, error) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return "", err
	}
	defer listener.Close()
	return fmt.Sprintf("%d", listener.Addr().(*net.TCPAddr).Port), nil
}

// StatusResponse matches the server's StatusResponse structure.
type StatusResponse struct {
	Server    string `json:"server"`
	Providers struct {
		OCR []string `json:"ocr"`
		LLM []string `json:"llm"`
	} `json:"providers"`
	Defra struct {
		Container string `json:"container"`
		Health    string `json:"health"`
		URL       string `json:"url"`
	} `json:"defra"`
}

// GetStatus fetches the /api/status endpoint and returns the parsed response.
func GetStatus(url string) (*StatusResponse, error) {
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Get(url + "/api/status")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var status StatusResponse
	if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
		return nil, err
	}
	return &status, nil
}
