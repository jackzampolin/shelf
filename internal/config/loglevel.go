package config

import (
	"fmt"
	"log/slog"
	"os"
	"strings"
)

// ParseLogLevel converts a string log level to slog.Level.
// Supports: debug, info, warn, error (case-insensitive).
func ParseLogLevel(level string) (slog.Level, error) {
	switch strings.ToLower(level) {
	case "debug":
		return slog.LevelDebug, nil
	case "info":
		return slog.LevelInfo, nil
	case "warn", "warning":
		return slog.LevelWarn, nil
	case "error":
		return slog.LevelError, nil
	default:
		return slog.LevelInfo, fmt.Errorf("invalid log level %q: must be debug, info, warn, or error", level)
	}
}

// ResolveLogLevel returns the effective log level, checking:
// 1. The provided value (CLI flag)
// 2. Environment variable (SHELF_LOG_LEVEL)
// 3. Default (info)
func ResolveLogLevel(flagValue string) slog.Level {
	level := flagValue
	if level == "" {
		level = os.Getenv("SHELF_LOG_LEVEL")
	}
	if level == "" {
		level = "info"
	}

	parsed, err := ParseLogLevel(level)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Warning: %v, using info\n", err)
		return slog.LevelInfo
	}
	return parsed
}
