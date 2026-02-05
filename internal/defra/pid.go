package defra

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"syscall"
)

// WritePidFile writes the current process ID to the given path.
func WritePidFile(path string) error {
	return os.WriteFile(path, []byte(strconv.Itoa(os.Getpid())), 0o644)
}

// RemovePidFile removes the PID file at the given path.
func RemovePidFile(path string) {
	_ = os.Remove(path)
}

// ReadPidFile reads the process ID from the given PID file.
func ReadPidFile(path string) (int, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, err
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		return 0, fmt.Errorf("invalid pid file contents: %w", err)
	}
	return pid, nil
}

// IsProcessAlive checks whether a process with the given PID is running.
func IsProcessAlive(pid int) bool {
	proc, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	// Signal 0 checks existence without sending a real signal.
	return proc.Signal(syscall.Signal(0)) == nil
}
