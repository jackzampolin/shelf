package defra

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/avast/retry-go/v4"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/api/types/image"
	"github.com/docker/docker/api/types/mount"
	"github.com/docker/docker/client"
	"github.com/docker/go-connections/nat"
)

const (
	DefaultImage         = "sourcenetwork/defradb:latest"
	DefaultContainerName = "shelf-defra"
	DefaultPort          = "9181"
	ContainerPort        = "9181/tcp"
	DataDir              = "/data"
	Label                = "shelf-defra"
)

// ContainerStatus represents the state of the DefraDB container.
type ContainerStatus string

const (
	StatusRunning    ContainerStatus = "running"
	StatusStopped    ContainerStatus = "stopped"
	StatusNotFound   ContainerStatus = "not_found"
	StatusUnhealthy  ContainerStatus = "unhealthy"
	StatusStarting   ContainerStatus = "starting"
)

// DockerManager manages the DefraDB Docker container lifecycle.
type DockerManager struct {
	cli           *client.Client
	containerName string
	imageName     string
	dataPath      string            // Host path for data persistence (~/.shelf/defradb)
	hostPort      string            // Host port to bind (default: 9181)
	labels        map[string]string // Container labels
}

// DockerConfig holds configuration for the Docker manager.
type DockerConfig struct {
	ContainerName string
	Image         string
	DataPath      string
	HostPort      string
	Labels        map[string]string // Optional labels for container (used for test cleanup)
}

// NewDockerManager creates a new Docker manager for DefraDB.
func NewDockerManager(cfg DockerConfig) (*DockerManager, error) {
	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		return nil, fmt.Errorf("failed to create docker client: %w", err)
	}

	// Set defaults
	if cfg.ContainerName == "" {
		cfg.ContainerName = DefaultContainerName
	}
	if cfg.Image == "" {
		cfg.Image = DefaultImage
	}
	if cfg.HostPort == "" {
		cfg.HostPort = DefaultPort
	}

	// Merge default label with any provided labels
	labels := map[string]string{Label: "true"}
	for k, v := range cfg.Labels {
		labels[k] = v
	}

	return &DockerManager{
		cli:           cli,
		containerName: cfg.ContainerName,
		imageName:     cfg.Image,
		dataPath:      cfg.DataPath,
		hostPort:      cfg.HostPort,
		labels:        labels,
	}, nil
}

// Close closes the Docker client.
func (m *DockerManager) Close() error {
	return m.cli.Close()
}

// Start starts the DefraDB container. Returns error if already running.
func (m *DockerManager) Start(ctx context.Context) error {
	// Check if Docker is running
	if _, err := m.cli.Ping(ctx); err != nil {
		return fmt.Errorf("docker is not running: %w", err)
	}

	// Check if container already exists
	status, containerID, err := m.getContainerStatus(ctx)
	if err != nil {
		return err
	}

	switch status {
	case StatusRunning:
		return nil // Already running
	case StatusStopped:
		// Start existing container
		if err := m.cli.ContainerStart(ctx, containerID, container.StartOptions{}); err != nil {
			return fmt.Errorf("failed to start existing container: %w", err)
		}
		return m.waitForReady(ctx, 30*time.Second)
	case StatusNotFound:
		// Create and start new container
		return m.createAndStart(ctx)
	default:
		return fmt.Errorf("container in unexpected state: %s", status)
	}
}

// Stop stops the DefraDB container.
func (m *DockerManager) Stop(ctx context.Context) error {
	status, containerID, err := m.getContainerStatus(ctx)
	if err != nil {
		return err
	}

	if status == StatusNotFound {
		return nil // Nothing to stop
	}

	timeout := 10
	if err := m.cli.ContainerStop(ctx, containerID, container.StopOptions{Timeout: &timeout}); err != nil {
		return fmt.Errorf("failed to stop container: %w", err)
	}

	return nil
}

// Remove stops and removes the DefraDB container.
func (m *DockerManager) Remove(ctx context.Context) error {
	status, containerID, err := m.getContainerStatus(ctx)
	if err != nil {
		return err
	}

	if status == StatusNotFound {
		return nil
	}

	// Stop first if running
	if status == StatusRunning {
		if err := m.Stop(ctx); err != nil {
			return err
		}
	}

	if err := m.cli.ContainerRemove(ctx, containerID, container.RemoveOptions{
		Force:         true,
		RemoveVolumes: true,
	}); err != nil {
		return fmt.Errorf("failed to remove container: %w", err)
	}

	return nil
}

// Status returns the current status of the DefraDB container.
func (m *DockerManager) Status(ctx context.Context) (ContainerStatus, error) {
	status, _, err := m.getContainerStatus(ctx)
	return status, err
}

// Logs returns the container logs.
func (m *DockerManager) Logs(ctx context.Context, tail string) (string, error) {
	status, containerID, err := m.getContainerStatus(ctx)
	if err != nil {
		return "", err
	}

	if status == StatusNotFound {
		return "", fmt.Errorf("container not found")
	}

	logs, err := m.cli.ContainerLogs(ctx, containerID, container.LogsOptions{
		ShowStdout: true,
		ShowStderr: true,
		Tail:       tail,
	})
	if err != nil {
		return "", fmt.Errorf("failed to get logs: %w", err)
	}
	defer logs.Close()

	logBytes, err := io.ReadAll(logs)
	if err != nil {
		return "", fmt.Errorf("failed to read logs: %w", err)
	}

	return string(logBytes), nil
}

// URL returns the DefraDB API URL.
func (m *DockerManager) URL() string {
	return fmt.Sprintf("http://localhost:%s", m.hostPort)
}

// ValidateExisting checks if an existing container matches our expected configuration.
// Returns nil if the container is compatible, or an error describing the mismatch.
func (m *DockerManager) ValidateExisting(ctx context.Context) error {
	status, containerID, err := m.getContainerStatus(ctx)
	if err != nil {
		return err
	}
	if status == StatusNotFound {
		return nil // No container to validate
	}

	// Inspect the container
	info, err := m.cli.ContainerInspect(ctx, containerID)
	if err != nil {
		return fmt.Errorf("failed to inspect container: %w", err)
	}

	// Check port binding
	bindings := info.HostConfig.PortBindings[ContainerPort]
	if len(bindings) == 0 {
		return fmt.Errorf("existing container has no port binding for %s", ContainerPort)
	}
	boundPort := bindings[0].HostPort
	if boundPort != m.hostPort {
		return fmt.Errorf("existing container bound to port %s, expected %s", boundPort, m.hostPort)
	}

	// Check data mount if we have a data path configured
	if m.dataPath != "" {
		foundMount := false
		for _, mnt := range info.Mounts {
			if mnt.Destination == DataDir {
				if mnt.Source != m.dataPath {
					return fmt.Errorf("existing container mounts %s, expected %s", mnt.Source, m.dataPath)
				}
				foundMount = true
				break
			}
		}
		if !foundMount {
			return fmt.Errorf("existing container has no mount for %s", DataDir)
		}
	}

	return nil
}

// WaitReady waits for DefraDB to be ready to accept requests.
func (m *DockerManager) WaitReady(ctx context.Context, timeout time.Duration) error {
	return m.waitForReady(ctx, timeout)
}

// createAndStart creates and starts a new DefraDB container.
func (m *DockerManager) createAndStart(ctx context.Context) error {
	// Pull image if needed
	if err := m.ensureImage(ctx); err != nil {
		return err
	}

	// Build container config
	containerConfig := &container.Config{
		Image: m.imageName,
		Cmd: []string{
			"start",
			"--no-keyring",
			"--url", "0.0.0.0:9181",
			"--store", "badger",
			"--rootdir", DataDir,
		},
		Labels: m.labels,
		ExposedPorts: nat.PortSet{
			ContainerPort: struct{}{},
		},
		Healthcheck: &container.HealthConfig{
			Test:        []string{"CMD", "curl", "-sf", "http://localhost:9181/health-check"},
			Interval:    2 * time.Second,
			Timeout:     5 * time.Second,
			Retries:     10,
			StartPeriod: 5 * time.Second,
		},
	}

	hostConfig := &container.HostConfig{
		PortBindings: nat.PortMap{
			ContainerPort: []nat.PortBinding{
				{HostIP: "127.0.0.1", HostPort: m.hostPort},
			},
		},
	}

	// Add data mount if path specified
	if m.dataPath != "" {
		hostConfig.Mounts = []mount.Mount{
			{
				Type:   mount.TypeBind,
				Source: m.dataPath,
				Target: DataDir,
			},
		}
	}

	resp, err := m.cli.ContainerCreate(ctx, containerConfig, hostConfig, nil, nil, m.containerName)
	if err != nil {
		return fmt.Errorf("failed to create container: %w", err)
	}

	if err := m.cli.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
		// Clean up on failure
		_ = m.cli.ContainerRemove(ctx, resp.ID, container.RemoveOptions{Force: true})
		return fmt.Errorf("failed to start container: %w", err)
	}

	return m.waitForReady(ctx, 30*time.Second)
}

// getContainerStatus returns the status and ID of the container.
func (m *DockerManager) getContainerStatus(ctx context.Context) (ContainerStatus, string, error) {
	filterArgs := filters.NewArgs()
	filterArgs.Add("name", m.containerName)

	containers, err := m.cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filterArgs,
	})
	if err != nil {
		return "", "", fmt.Errorf("failed to list containers: %w", err)
	}

	if len(containers) == 0 {
		return StatusNotFound, "", nil
	}

	c := containers[0]
	switch c.State {
	case "running":
		return StatusRunning, c.ID, nil
	case "exited", "dead":
		return StatusStopped, c.ID, nil
	case "created", "restarting":
		return StatusStarting, c.ID, nil
	default:
		return ContainerStatus(c.State), c.ID, nil
	}
}

// waitForReady polls DefraDB's health endpoint until ready.
func (m *DockerManager) waitForReady(ctx context.Context, timeout time.Duration) error {
	httpClient := &http.Client{Timeout: 2 * time.Second}
	url := m.URL() + "/health-check"

	return retry.Do(
		func() error {
			req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
			if err != nil {
				return err
			}
			resp, err := httpClient.Do(req)
			if err != nil {
				return err
			}
			_ = resp.Body.Close()
			if resp.StatusCode != http.StatusOK {
				return fmt.Errorf("unhealthy status: %d", resp.StatusCode)
			}
			return nil
		},
		retry.Context(ctx),
		retry.Attempts(uint(timeout.Seconds())),
		retry.Delay(1*time.Second),
	)
}

// ensureImage pulls the DefraDB image if not present.
func (m *DockerManager) ensureImage(ctx context.Context) error {
	_, err := m.cli.ImageInspect(ctx, m.imageName)
	if err == nil {
		return nil // Image exists
	}

	reader, err := m.cli.ImagePull(ctx, m.imageName, image.PullOptions{})
	if err != nil {
		return fmt.Errorf("failed to pull image: %w", err)
	}
	defer reader.Close()

	// Drain reader to complete pull
	_, err = io.Copy(io.Discard, reader)
	return err
}
