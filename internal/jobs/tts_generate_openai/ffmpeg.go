package tts_generate_openai

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
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

// GetAudioDuration uses ffprobe to get the duration of an audio file in milliseconds.
func GetAudioDuration(ctx context.Context, audioPath string) (int, error) {
	cmd := exec.CommandContext(ctx, "ffprobe",
		"-v", "error",
		"-show_entries", "format=duration",
		"-of", "default=noprint_wrappers=1:nokey=1",
		audioPath,
	)

	output, err := cmd.Output()
	if err != nil {
		return 0, fmt.Errorf("ffprobe failed: %w", err)
	}

	// Parse duration (in seconds with decimal)
	var durationSec float64
	if _, err := fmt.Sscanf(strings.TrimSpace(string(output)), "%f", &durationSec); err != nil {
		return 0, fmt.Errorf("failed to parse duration: %w", err)
	}

	return int(durationSec * 1000), nil
}

// CheckFFmpegAvailable checks if ffmpeg and ffprobe are available.
func CheckFFmpegAvailable() error {
	if _, err := exec.LookPath("ffmpeg"); err != nil {
		return fmt.Errorf("ffmpeg not found in PATH: %w", err)
	}
	if _, err := exec.LookPath("ffprobe"); err != nil {
		return fmt.Errorf("ffprobe not found in PATH: %w", err)
	}
	return nil
}

// CleanupChapterSegments removes individual segment files after concatenation.
func CleanupChapterSegments(chapterDir string) error {
	entries, err := os.ReadDir(chapterDir)
	if err != nil {
		return err
	}

	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		// Only remove segment files
		name := entry.Name()
		if strings.HasPrefix(name, "segment_") {
			os.Remove(filepath.Join(chapterDir, name))
		}
	}

	return nil
}
