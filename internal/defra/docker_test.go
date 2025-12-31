package defra

import (
	"context"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/testutil"
)

func TestDockerConfig_Defaults(t *testing.T) {
	if DefaultContainerName != "shelf-defra" {
		t.Errorf("unexpected default container name: %s", DefaultContainerName)
	}
	if DefaultImage != "sourcenetwork/defradb:latest" {
		t.Errorf("unexpected default image: %s", DefaultImage)
	}
	if DefaultPort != "9181" {
		t.Errorf("unexpected default port: %s", DefaultPort)
	}
}

func TestGenerateContainerName(t *testing.T) {
	tests := []struct {
		name     string
		homePath string
		want     string
	}{
		{
			name:     "typical home path",
			homePath: "/home/user/.shelf",
			want:     "shelf-defra-75643996", // sha256("/home/user/.shelf")[:8]
		},
		{
			name:     "different home path",
			homePath: "/Users/john/.shelf",
			want:     "shelf-defra-72909148", // sha256("/Users/john/.shelf")[:8]
		},
		{
			name:     "empty path",
			homePath: "",
			want:     "shelf-defra-e3b0c442", // sha256("")[:8]
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := GenerateContainerName(tt.homePath)

			// Check prefix
			if !hasPrefix(got, ContainerNamePrefix) {
				t.Errorf("GenerateContainerName() = %q, want prefix %q", got, ContainerNamePrefix)
			}

			// Check total length (prefix + 8 char hash)
			wantLen := len(ContainerNamePrefix) + 8
			if len(got) != wantLen {
				t.Errorf("GenerateContainerName() length = %d, want %d", len(got), wantLen)
			}

			// Check expected value
			if got != tt.want {
				t.Errorf("GenerateContainerName(%q) = %q, want %q", tt.homePath, got, tt.want)
			}
		})
	}
}

func TestGenerateContainerName_Deterministic(t *testing.T) {
	homePath := "/Users/test/.shelf"

	first := GenerateContainerName(homePath)
	second := GenerateContainerName(homePath)

	if first != second {
		t.Errorf("GenerateContainerName() not deterministic: %q != %q", first, second)
	}
}

func TestGenerateContainerName_UniquePerPath(t *testing.T) {
	path1 := "/home/user1/.shelf"
	path2 := "/home/user2/.shelf"

	name1 := GenerateContainerName(path1)
	name2 := GenerateContainerName(path2)

	if name1 == name2 {
		t.Errorf("GenerateContainerName() should produce unique names: %q == %q", name1, name2)
	}
}

func hasPrefix(s, prefix string) bool {
	return len(s) >= len(prefix) && s[:len(prefix)] == prefix
}

func TestNewDockerManager_ContainerNaming(t *testing.T) {
	tests := []struct {
		name         string
		cfg          DockerConfig
		wantContName string
	}{
		{
			name:         "explicit container name takes precedence",
			cfg:          DockerConfig{ContainerName: "my-custom-container", HomePath: "/home/test/.shelf"},
			wantContName: "my-custom-container",
		},
		{
			name:         "generates name from home path when no explicit name",
			cfg:          DockerConfig{HomePath: "/home/test/.shelf"},
			wantContName: GenerateContainerName("/home/test/.shelf"),
		},
		{
			name:         "falls back to default when no name or home path",
			cfg:          DockerConfig{},
			wantContName: DefaultContainerName,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mgr, err := NewDockerManager(tt.cfg)
			if err != nil {
				t.Fatalf("NewDockerManager() error = %v", err)
			}
			defer mgr.Close()

			if mgr.ContainerName() != tt.wantContName {
				t.Errorf("ContainerName() = %q, want %q", mgr.ContainerName(), tt.wantContName)
			}
		})
	}
}

func TestContainerStatus_Values(t *testing.T) {
	statuses := []ContainerStatus{
		StatusRunning,
		StatusStopped,
		StatusNotFound,
		StatusUnhealthy,
		StatusStarting,
	}

	seen := make(map[ContainerStatus]bool)
	for _, s := range statuses {
		if seen[s] {
			t.Errorf("duplicate status value: %s", s)
		}
		seen[s] = true
	}
}

func TestDockerManager_Integration(t *testing.T) {
	// Register cleanup for test containers
	_ = testutil.DockerClient(t)

	ctx := context.Background()
	dataPath := t.TempDir()
	containerName := testutil.UniqueContainerName(t, "defra")
	port, err := testutil.FindFreePort()
	if err != nil {
		t.Fatalf("failed to find free port: %v", err)
	}

	mgr, err := NewDockerManager(DockerConfig{
		ContainerName: containerName,
		DataPath:      dataPath,
		HostPort:      port,
		Labels:        testutil.ContainerLabels(t),
	})
	if err != nil {
		t.Fatalf("NewDockerManager() error = %v", err)
	}
	defer mgr.Close()

	t.Run("Start", func(t *testing.T) {
		if err := mgr.Start(ctx); err != nil {
			t.Fatalf("Start() error = %v", err)
		}

		status, err := mgr.Status(ctx)
		if err != nil {
			t.Fatalf("Status() error = %v", err)
		}
		if status != StatusRunning {
			t.Errorf("expected status running, got %s", status)
		}
	})

	t.Run("Start_AlreadyRunning", func(t *testing.T) {
		if err := mgr.Start(ctx); err != nil {
			t.Errorf("Start() on running container should succeed: %v", err)
		}
	})

	t.Run("HealthCheck", func(t *testing.T) {
		client := NewClient(mgr.URL())
		if err := client.HealthCheck(ctx); err != nil {
			t.Errorf("HealthCheck() error = %v", err)
		}
	})

	t.Run("Stop", func(t *testing.T) {
		if err := mgr.Stop(ctx); err != nil {
			t.Fatalf("Stop() error = %v", err)
		}

		status, err := mgr.Status(ctx)
		if err != nil {
			t.Fatalf("Status() error = %v", err)
		}
		if status != StatusStopped {
			t.Errorf("expected status stopped, got %s", status)
		}
	})

	t.Run("Stop_AlreadyStopped", func(t *testing.T) {
		if err := mgr.Stop(ctx); err != nil {
			t.Errorf("Stop() on stopped container should succeed: %v", err)
		}
	})

	t.Run("Restart", func(t *testing.T) {
		if err := mgr.Start(ctx); err != nil {
			t.Fatalf("Start() error = %v", err)
		}

		status, err := mgr.Status(ctx)
		if err != nil {
			t.Fatalf("Status() error = %v", err)
		}
		if status != StatusRunning {
			t.Errorf("expected status running, got %s", status)
		}
	})

	t.Run("Logs", func(t *testing.T) {
		logs, err := mgr.Logs(ctx, "10")
		if err != nil {
			t.Fatalf("Logs() error = %v", err)
		}
		if len(logs) == 0 {
			t.Error("expected some log output")
		}
	})

	t.Run("Remove", func(t *testing.T) {
		if err := mgr.Remove(ctx); err != nil {
			t.Fatalf("Remove() error = %v", err)
		}

		status, err := mgr.Status(ctx)
		if err != nil {
			t.Fatalf("Status() error = %v", err)
		}
		if status != StatusNotFound {
			t.Errorf("expected status not_found, got %s", status)
		}
	})

	t.Run("Remove_NotFound", func(t *testing.T) {
		if err := mgr.Remove(ctx); err != nil {
			t.Errorf("Remove() on non-existent container should succeed: %v", err)
		}
	})

	t.Run("Logs_NotFound", func(t *testing.T) {
		_, err := mgr.Logs(ctx, "10")
		if err == nil {
			t.Error("expected error for non-existent container")
		}
	})
}

func TestDockerManager_ContextCancellation(t *testing.T) {
	// Register cleanup for test containers
	_ = testutil.DockerClient(t)

	dataPath := t.TempDir()
	containerName := testutil.UniqueContainerName(t, "cancel")
	port, err := testutil.FindFreePort()
	if err != nil {
		t.Fatalf("failed to find free port: %v", err)
	}

	mgr, err := NewDockerManager(DockerConfig{
		ContainerName: containerName,
		DataPath:      dataPath,
		HostPort:      port,
		Labels:        testutil.ContainerLabels(t),
	})
	if err != nil {
		t.Fatalf("NewDockerManager() error = %v", err)
	}
	defer mgr.Close()

	t.Run("Start_Cancelled", func(t *testing.T) {
		ctx, cancel := context.WithCancel(context.Background())
		cancel() // Cancel immediately

		err := mgr.Start(ctx)
		if err == nil {
			_ = mgr.Remove(context.Background())
			t.Error("expected error from cancelled context")
		}
	})

	t.Run("WaitReady_Timeout", func(t *testing.T) {
		ctx, cancel := context.WithTimeout(context.Background(), 1*time.Millisecond)
		defer cancel()

		err := mgr.WaitReady(ctx, 1*time.Millisecond)
		if err == nil {
			t.Error("expected timeout error")
		}
	})
}
