package home

import (
	"fmt"
	"os"
	"path/filepath"
)

const (
	// DefaultDirName is the default name for the shelf home directory.
	DefaultDirName = ".shelf"

	// DataDirName is the subdirectory for book data and scans.
	DataDirName = "data"

	// ConfigFileName is the default config file name.
	ConfigFileName = "config.yaml"
)

// Dir represents the shelf home directory structure.
type Dir struct {
	path string
}

// New creates a new Dir with the given path.
// If path is empty, uses the default (~/.shelf).
func New(path string) (*Dir, error) {
	if path == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return nil, fmt.Errorf("failed to get user home directory: %w", err)
		}
		path = filepath.Join(home, DefaultDirName)
	}

	return &Dir{path: path}, nil
}

// Path returns the root path of the home directory.
func (d *Dir) Path() string {
	return d.path
}

// DataPath returns the path to the data directory.
func (d *Dir) DataPath() string {
	return filepath.Join(d.path, DataDirName)
}

// ConfigPath returns the path to the default config file.
func (d *Dir) ConfigPath() string {
	return filepath.Join(d.path, ConfigFileName)
}

// EnsureExists creates the home directory and subdirectories if they don't exist.
func (d *Dir) EnsureExists() error {
	// Create data directory (this also creates the parent)
	if err := os.MkdirAll(d.DataPath(), 0o755); err != nil {
		return fmt.Errorf("failed to create data directory: %w", err)
	}
	return nil
}

// Exists returns true if the home directory exists.
func (d *Dir) Exists() bool {
	_, err := os.Stat(d.path)
	return err == nil
}

// ConfigExists returns true if the config file exists in the home directory.
func (d *Dir) ConfigExists() bool {
	_, err := os.Stat(d.ConfigPath())
	return err == nil
}
