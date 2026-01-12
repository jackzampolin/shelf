package home

import (
	"os"
	"path/filepath"
	"testing"
)

func TestNew(t *testing.T) {
	t.Run("with explicit path", func(t *testing.T) {
		dir, err := New("/tmp/test-shelf")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if dir.Path() != "/tmp/test-shelf" {
			t.Errorf("expected path /tmp/test-shelf, got %s", dir.Path())
		}
	})

	t.Run("with empty path uses default", func(t *testing.T) {
		dir, err := New("")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}

		home, _ := os.UserHomeDir()
		expected := filepath.Join(home, DefaultDirName)
		if dir.Path() != expected {
			t.Errorf("expected path %s, got %s", expected, dir.Path())
		}
	})
}

func TestDir_Paths(t *testing.T) {
	dir, _ := New("/tmp/test-shelf")

	t.Run("DataPath", func(t *testing.T) {
		expected := "/tmp/test-shelf/data"
		if dir.DataPath() != expected {
			t.Errorf("expected %s, got %s", expected, dir.DataPath())
		}
	})

	t.Run("ConfigPath", func(t *testing.T) {
		expected := "/tmp/test-shelf/config.yaml"
		if dir.ConfigPath() != expected {
			t.Errorf("expected %s, got %s", expected, dir.ConfigPath())
		}
	})
}

func TestDir_EnsureExists(t *testing.T) {
	// Use a temp directory
	tmpDir := t.TempDir()
	shelfDir := filepath.Join(tmpDir, "shelf-test")

	dir, err := New(shelfDir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Directory shouldn't exist yet
	if dir.Exists() {
		t.Error("directory should not exist before EnsureExists")
	}

	// Create it
	if err := dir.EnsureExists(); err != nil {
		t.Fatalf("EnsureExists failed: %v", err)
	}

	// Now it should exist
	if !dir.Exists() {
		t.Error("directory should exist after EnsureExists")
	}

	// Data directory should also exist
	if _, err := os.Stat(dir.DataPath()); os.IsNotExist(err) {
		t.Error("data directory should exist after EnsureExists")
	}
}

func TestDir_ConfigExists(t *testing.T) {
	tmpDir := t.TempDir()
	dir, _ := New(tmpDir)

	// Config doesn't exist
	if dir.ConfigExists() {
		t.Error("config should not exist initially")
	}

	// Create a config file
	configPath := dir.ConfigPath()
	if err := os.WriteFile(configPath, []byte("test: true\n"), 0644); err != nil {
		t.Fatalf("failed to create test config: %v", err)
	}

	// Now it should exist
	if !dir.ConfigExists() {
		t.Error("config should exist after creation")
	}
}
