package tts_generate

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs"
)

// Task names for chapter audio concatenation. Each provider strategy pins its
// own task name so persisted work units keep routing to the right handler.
const (
	// TaskConcatenateChapter is the ElevenLabs chapter concatenation task.
	TaskConcatenateChapter = "concatenate_chapter"
	// TaskConcatenateChapterOpenAI is the OpenAI chapter concatenation task.
	TaskConcatenateChapterOpenAI = "concatenate_chapter_openai"
)

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

		chapterDocID, ok := data["chapter_doc_id"].(string)
		if !ok || chapterDocID == "" {
			return nil, fmt.Errorf("chapter_doc_id required for concatenate task")
		}

		format, _ := data["format"].(string)
		if format == "" {
			format = "mp3_44100_128"
		}

		outputPath, err := ConcatenateChapterAudio(ctx, bookID, chapterDocID, homeDir, format)
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
