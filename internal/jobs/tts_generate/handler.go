package tts_generate

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs"
)

// TaskConcatenateChapter is the task name for chapter audio concatenation.
const TaskConcatenateChapter = "concatenate_chapter"

// ConcatenateHandler returns a CPUTaskHandler for concatenating chapter audio.
func ConcatenateHandler(homeDir *home.Dir) jobs.CPUTaskHandler {
	return func(ctx context.Context, req *jobs.CPUWorkRequest) (*jobs.CPUWorkResult, error) {
		data, ok := req.Data.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("invalid data for concatenate task")
		}

		bookID, ok := data["book_id"].(string)
		if !ok || bookID == "" {
			return nil, fmt.Errorf("book_id required for concatenate task")
		}

		chapterIdx, ok := data["chapter_idx"].(int)
		if !ok {
			// Try float64 (JSON unmarshaling produces float64)
			if f, ok := data["chapter_idx"].(float64); ok {
				chapterIdx = int(f)
			} else {
				return nil, fmt.Errorf("chapter_idx required for concatenate task")
			}
		}

		format, _ := data["format"].(string)
		if format == "" {
			format = "mp3"
		}

		outputPath, err := ConcatenateChapterAudio(ctx, bookID, chapterIdx, homeDir, format)
		if err != nil {
			return nil, fmt.Errorf("concatenation failed: %w", err)
		}

		return &jobs.CPUWorkResult{
			Data: map[string]any{
				"output_path": outputPath,
			},
		}, nil
	}
}
