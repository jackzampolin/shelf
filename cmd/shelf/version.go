package main

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/version"
)

var versionCmd = &cobra.Command{
	Use:   "version",
	Short: "Print version information",
	Run: func(cmd *cobra.Command, args []string) {
		fmt.Printf("shelf %s\n", version.GitRelease)
		fmt.Printf("  Go:     %s\n", version.GoInfo)
		fmt.Printf("  Commit: %s\n", version.GitCommit)
		fmt.Printf("  Date:   %s\n", version.GitCommitDate)
	},
}
