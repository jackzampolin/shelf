package endpoints

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// DownloadChapterAudioEndpoint handles GET /api/books/{book_id}/audio/{chapter}/download.
type DownloadChapterAudioEndpoint struct{}

func (e *DownloadChapterAudioEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{book_id}/audio/{chapter}/download", e.handler
}

func (e *DownloadChapterAudioEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Download chapter audio
//	@Description	Download the generated audio file for a chapter
//	@Tags			books,audio
//	@Produce		audio/mpeg
//	@Param			book_id	path		string	true	"Book ID"
//	@Param			chapter	path		int		true	"Chapter index"
//	@Success		200		{file}		file
//	@Failure		400		{object}	ErrorResponse
//	@Failure		404		{object}	ErrorResponse
//	@Router			/api/books/{book_id}/audio/{chapter}/download [get]
func (e *DownloadChapterAudioEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	if err := defra.ValidateID(bookID); err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid book_id: %v", err))
		return
	}

	chapterStr := r.PathValue("chapter")
	chapterIdx, err := strconv.Atoi(chapterStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid chapter index")
		return
	}

	ctx := r.Context()
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	record, err := queryChapterAudioRecordForChapter(ctx, defraClient, bookID, chapterIdx)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to query chapter audio: %v", err))
		return
	}
	if record == nil {
		writeError(w, http.StatusNotFound, fmt.Sprintf("no audio record found for chapter %d", chapterIdx))
		return
	}

	audioPath := getString(record, "audio_file")
	if audioPath == "" {
		writeError(w, http.StatusNotFound, fmt.Sprintf("audio file not found for chapter %d", chapterIdx))
		return
	}

	// Verify file exists
	if _, err := os.Stat(audioPath); os.IsNotExist(err) {
		writeError(w, http.StatusNotFound, fmt.Sprintf("audio file missing on disk: %s", audioPath))
		return
	}

	// Determine content type from extension
	ext := filepath.Ext(audioPath)
	contentType := "audio/mpeg"
	switch ext {
	case ".wav":
		contentType = "audio/wav"
	case ".ogg", ".opus":
		contentType = "audio/ogg"
	case ".flac":
		contentType = "audio/flac"
	}

	// Serve file
	filename := filepath.Base(audioPath)
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filename))
	http.ServeFile(w, r, audioPath)
}

func (e *DownloadChapterAudioEndpoint) Command(getServerURL func() string) *cobra.Command {
	var outputPath string
	cmd := &cobra.Command{
		Use:   "download-audio <book_id> <chapter_idx>",
		Short: "Download chapter audio file",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]
			chapterIdx := args[1]

			client := api.NewClient(getServerURL())
			data, err := client.GetRaw(ctx, fmt.Sprintf("/api/books/%s/audio/%s/download", bookID, chapterIdx))
			if err != nil {
				return err
			}

			if outputPath == "" {
				outputPath = fmt.Sprintf("chapter_%s.mp3", chapterIdx)
			}

			if err := os.WriteFile(outputPath, data, 0644); err != nil {
				return fmt.Errorf("failed to write file: %w", err)
			}

			fmt.Printf("Downloaded to: %s\n", outputPath)
			return nil
		},
	}
	cmd.Flags().StringVarP(&outputPath, "output", "o", "", "Output file path")
	return cmd
}

func queryChapterAudioRecords(ctx context.Context, client *defra.Client, bookID string) ([]map[string]any, error) {
	primaryQuery := fmt.Sprintf(`{
		ChapterAudio(filter: {_bookID: {_eq: "%s"}}) {
			unique_key
			chapter_idx
			duration_ms
			segment_count
			total_cost_usd
			audio_file
		}
	}`, bookID)
	primaryResp, primaryErr := client.Execute(ctx, primaryQuery, nil)
	if primaryErr == nil {
		records := extractDocMaps(primaryResp.Data, "ChapterAudio")
		if len(records) > 0 {
			return records, nil
		}
	}

	const pageSize = 1000
	var filtered []map[string]any
	for offset := 0; ; offset += pageSize {
		fallbackQuery := fmt.Sprintf(`{
			ChapterAudio(limit: %d, offset: %d, order: {unique_key: ASC}) {
				unique_key
				chapter_idx
				duration_ms
				segment_count
				total_cost_usd
				audio_file
			}
		}`, pageSize, offset)
		fallbackResp, fallbackErr := client.Execute(ctx, fallbackQuery, nil)
		if fallbackErr != nil {
			if primaryErr != nil {
				return nil, primaryErr
			}
			return nil, fallbackErr
		}
		batch := filterChapterAudioByBookID(extractDocMaps(fallbackResp.Data, "ChapterAudio"), bookID)
		filtered = append(filtered, batch...)
		batchRaw := extractDocMaps(fallbackResp.Data, "ChapterAudio")
		if len(batchRaw) < pageSize {
			break
		}
	}
	return filtered, nil
}

func queryChapterAudioRecordForChapter(ctx context.Context, client *defra.Client, bookID string, chapterIdx int) (map[string]any, error) {
	primaryQuery := fmt.Sprintf(`{
		ChapterAudio(filter: {_bookID: {_eq: "%s"}, chapter_idx: {_eq: %d}}) {
			unique_key
			chapter_idx
			audio_file
		}
	}`, bookID, chapterIdx)
	primaryResp, primaryErr := client.Execute(ctx, primaryQuery, nil)
	if primaryErr == nil {
		records := extractDocMaps(primaryResp.Data, "ChapterAudio")
		if len(records) > 0 {
			return records[0], nil
		}
	}

	const pageSize = 200
	for offset := 0; ; offset += pageSize {
		fallbackQuery := fmt.Sprintf(`{
			ChapterAudio(filter: {chapter_idx: {_eq: %d}}, limit: %d, offset: %d, order: {unique_key: ASC}) {
				unique_key
				chapter_idx
				audio_file
			}
		}`, chapterIdx, pageSize, offset)
		fallbackResp, fallbackErr := client.Execute(ctx, fallbackQuery, nil)
		if fallbackErr != nil {
			if primaryErr != nil {
				return nil, primaryErr
			}
			return nil, fallbackErr
		}

		batchRaw := extractDocMaps(fallbackResp.Data, "ChapterAudio")
		records := filterChapterAudioByBookID(batchRaw, bookID)
		if len(records) > 0 {
			return records[0], nil
		}
		if len(batchRaw) < pageSize {
			break
		}
	}
	return nil, nil
}

func filterChapterAudioByBookID(records []map[string]any, bookID string) []map[string]any {
	prefix := bookID + ":"
	filtered := make([]map[string]any, 0, len(records))
	for _, rec := range records {
		if strings.HasPrefix(getString(rec, "unique_key"), prefix) {
			filtered = append(filtered, rec)
		}
	}
	return filtered
}

func extractDocMaps(data map[string]any, key string) []map[string]any {
	raw, ok := data[key].([]any)
	if !ok {
		return nil
	}
	out := make([]map[string]any, 0, len(raw))
	for _, item := range raw {
		doc, ok := item.(map[string]any)
		if !ok {
			continue
		}
		out = append(out, doc)
	}
	return out
}
