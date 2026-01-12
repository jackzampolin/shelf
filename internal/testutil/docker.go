package testutil

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/client"
)

const (
	// CleanupLabel is used to identify resources created by tests
	CleanupLabel = "shelf-test"
)

// TestingT is a subset of testing.T used for Docker setup
type TestingT interface {
	Name() string
	Cleanup(func())
	Logf(format string, args ...any)
	Helper()
}

// DockerClient creates a Docker client and registers cleanup for test containers.
// It cleans up any orphaned containers from previous interrupted runs with the same test name.
func DockerClient(t TestingT) *client.Client {
	t.Helper()

	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		panic(fmt.Sprintf("failed to create docker client: %v", err))
	}

	// Verify Docker is running
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if _, err := cli.Ping(ctx); err != nil {
		panic(fmt.Sprintf("docker is not running: %v", err))
	}

	// Register cleanup for this test's containers
	t.Cleanup(func() {
		cleanupTestContainers(t, cli)
	})

	return cli
}

// UniqueContainerName generates a unique container name for a test.
// Format: shelf-test-<testname>-<random>
func UniqueContainerName(t TestingT, prefix string) string {
	t.Helper()
	return fmt.Sprintf("shelf-test-%s-%s-%s", prefix, sanitizeName(t.Name()), randString(4))
}

// ContainerLabels returns labels to apply to test containers.
// These labels are used for cleanup.
func ContainerLabels(t TestingT) map[string]string {
	return map[string]string{
		CleanupLabel: t.Name(),
	}
}

// cleanupTestContainers removes all containers created by this test.
func cleanupTestContainers(t TestingT, cli *client.Client) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	// Find containers with our label AND this specific test name
	filterArgs := filters.NewArgs()
	filterArgs.Add("label", fmt.Sprintf("%s=%s", CleanupLabel, t.Name()))

	containers, err := cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filterArgs,
	})
	if err != nil {
		t.Logf("Failed to list containers for cleanup: %v", err)
		return
	}

	for _, c := range containers {
		// Stop container
		timeout := 10
		if err := cli.ContainerStop(ctx, c.ID, container.StopOptions{Timeout: &timeout}); err != nil {
			t.Logf("Failed to stop container %s: %v", c.Names[0], err)
		}

		// Remove container
		if err := cli.ContainerRemove(ctx, c.ID, container.RemoveOptions{
			Force:         true,
			RemoveVolumes: true,
		}); err != nil {
			t.Logf("Failed to remove container %s: %v", c.Names[0], err)
		} else {
			t.Logf("Cleaned up container: %s", c.Names[0])
		}
	}
}

// CleanupAllTestContainers removes ALL shelf-test containers.
// Use sparingly - mainly for cleaning up after interrupted test runs.
func CleanupAllTestContainers(ctx context.Context) error {
	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		return fmt.Errorf("failed to create docker client: %w", err)
	}
	defer cli.Close()

	filterArgs := filters.NewArgs()
	filterArgs.Add("label", CleanupLabel)

	containers, err := cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filterArgs,
	})
	if err != nil {
		return fmt.Errorf("failed to list containers: %w", err)
	}

	for _, c := range containers {
		timeout := 10
		_ = cli.ContainerStop(ctx, c.ID, container.StopOptions{Timeout: &timeout})
		if err := cli.ContainerRemove(ctx, c.ID, container.RemoveOptions{
			Force:         true,
			RemoveVolumes: true,
		}); err != nil {
			return fmt.Errorf("failed to remove container %s: %w", c.Names[0], err)
		}
	}

	return nil
}

// randString generates a random hex string of n bytes
func randString(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// sanitizeName converts a test name to a valid container name component
func sanitizeName(name string) string {
	result := make([]byte, 0, len(name))
	for i := 0; i < len(name); i++ {
		c := name[i]
		if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') {
			result = append(result, c)
		} else if c == '/' || c == '_' || c == '-' {
			result = append(result, '-')
		}
	}
	// Limit length
	if len(result) > 30 {
		result = result[:30]
	}
	return string(result)
}
