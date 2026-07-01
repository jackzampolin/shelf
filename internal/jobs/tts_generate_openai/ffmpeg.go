package tts_generate_openai

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// concatenateWithFFmpeg uses ffmpeg to concatenate audio files.
// This creates a concat list file and uses ffmpeg's concat demuxer.
func concatenateWithFFmpeg(ctx context.Context, inputFiles []string, outputPath string) error {
	if len(inputFiles) == 0 {
		return fmt.Errorf("no input files provided")
	}

	// Single file case - just copy
	if len(inputFiles) == 1 {
		data, err := os.ReadFile(inputFiles[0])
		if err != nil {
			return fmt.Errorf("failed to read single input file: %w", err)
		}
		return os.WriteFile(outputPath, data, 0644)
	}

	// Create concat list file
	listPath := outputPath + ".txt"
	var lines []string
	for _, f := range inputFiles {
		// FFmpeg concat demuxer requires escaped paths
		escapedPath := strings.ReplaceAll(f, "'", "'\\''")
		lines = append(lines, fmt.Sprintf("file '%s'", escapedPath))
	}

	if err := os.WriteFile(listPath, []byte(strings.Join(lines, "\n")), 0644); err != nil {
		return fmt.Errorf("failed to create concat list: %w", err)
	}
	defer os.Remove(listPath)

	// Run ffmpeg
	// -f concat: use concat demuxer
	// -safe 0: allow absolute paths
	// -i: input file (the list)
	// -c copy: copy streams without re-encoding
	// -y: overwrite output
	cmd := exec.CommandContext(ctx, "ffmpeg",
		"-f", "concat",
		"-safe", "0",
		"-i", listPath,
		"-c", "copy",
		"-y",
		outputPath,
	)

	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("ffmpeg failed: %w\nOutput: %s", err, string(output))
	}

	return nil
}
