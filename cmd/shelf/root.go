package main

import (
	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/version"
)

var (
	cfgFile      string
	homeDir      string
	outputFormat string
)

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

	// Set output format before any command runs
	rootCmd.PersistentPreRun = func(cmd *cobra.Command, args []string) {
		api.SetOutputFormat(outputFormat)
	}

	rootCmd.AddCommand(versionCmd)
}
