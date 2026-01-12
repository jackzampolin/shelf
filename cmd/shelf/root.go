package main

import (
	"fmt"
	"log/slog"
	"os"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/version"
)

var (
	cfgFile      string
	homeDir      string
	outputFormat string
	logLevel     string
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

// GetLogLevel returns the configured log level, checking:
// 1. CLI flag (--log-level)
// 2. Environment variable (SHELF_LOG_LEVEL)
// 3. Default (info)
func GetLogLevel() slog.Level {
	level := logLevel
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

// IsDebugLevel returns true if the configured log level is debug.
func IsDebugLevel() bool {
	return GetLogLevel() == slog.LevelDebug
}

var rootCmd = &cobra.Command{
	Use:   "shelf",
	Short: "Book digitization pipeline with LLM-powered OCR and structuring",
	Long: `Shelf is a book digitization pipeline that transforms scanned book pages
into structured ePub files using LLM-powered OCR and content analysis.

The pipeline includes:
  - Multi-provider OCR with consensus blending
  - Page structure labeling (headers, body, footnotes, etc.)
  - Table of contents extraction and linking
  - ePub generation with proper formatting`,
	Version: version.GitRelease,
}

func init() {
	rootCmd.PersistentFlags().StringVar(
		&cfgFile, "config", "", "config file (default: ./config.yaml or ~/.shelf/config.yaml)",
	)
	rootCmd.PersistentFlags().StringVar(
		&homeDir, "home", "", "shelf home directory (default: ~/.shelf)",
	)
	rootCmd.PersistentFlags().StringVarP(
		&outputFormat, "output", "o", "yaml", "output format: yaml or json",
	)
	rootCmd.PersistentFlags().StringVar(
		&logLevel, "log-level", "", "log level: debug, info, warn, error (default: info, env: SHELF_LOG_LEVEL)",
	)

	// Set output format before any command runs
	rootCmd.PersistentPreRun = func(cmd *cobra.Command, args []string) {
		api.SetOutputFormat(outputFormat)
	}

	rootCmd.AddCommand(versionCmd)
}
