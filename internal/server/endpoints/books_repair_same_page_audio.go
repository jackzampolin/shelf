package endpoints

import (
	"fmt"
	"net/http"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

type RepairSamePageAudioEntry struct {
	ChapterID string `json:"chapter_id"`
	EntryID   string `json:"entry_id,omitempty"`
	Title     string `json:"title"`
	StartPage int    `json:"start_page"`
	Reason    string `json:"reason"`
	CID       string `json:"cid,omitempty"`
}

type RepairSamePageAudioResponse struct {
	BookID  string                     `json:"book_id"`
	Status  string                     `json:"status"`
	Changed int                        `json:"changed"`
	Entries []RepairSamePageAudioEntry `json:"entries"`
}

// RepairSamePageAudioEndpoint applies the deterministic page-owner rule to an
// already structured book without rerunning OCR, ToC, classification, or polish.
type RepairSamePageAudioEndpoint struct{}

func (e *RepairSamePageAudioEndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/{book_id}/repair-same-page-audio", e.handler
}

func (e *RepairSamePageAudioEndpoint) RequiresInit() bool { return true }

func (e *RepairSamePageAudioEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}
	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	query := fmt.Sprintf(`{
		Book(docID: %q) {
			_docID
			status
			structure_complete
			structure_failed
		}
		Chapter(filter: {book: {_docID: {_eq: %q}}}) {
			_docID
			entry_id
			title
			start_page
			sort_order
			audio_include
			audio_include_reasoning
		}
	}`, bookID, bookID)
	resp, err := client.Query(r.Context(), query)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if errMsg := resp.Error(); errMsg != "" {
		writeError(w, http.StatusInternalServerError, errMsg)
		return
	}

	books, _ := resp.Data["Book"].([]any)
	if len(books) == 0 {
		writeError(w, http.StatusNotFound, "book not found")
		return
	}
	book, ok := books[0].(map[string]any)
	if !ok {
		writeError(w, http.StatusInternalServerError, "unexpected book response format")
		return
	}
	status := strings.ToLower(getString(book, "status"))
	if (status != "complete" && status != "completed") ||
		!getBool(book, "structure_complete") || getBool(book, "structure_failed") {
		writeError(w, http.StatusConflict, "book must be terminally structure-complete before same-page audio repair")
		return
	}

	rawChapters, _ := resp.Data["Chapter"].([]any)
	chapters := make([]*common.ChapterState, 0, len(rawChapters))
	for _, raw := range rawChapters {
		chapter, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		chapters = append(chapters, &common.ChapterState{
			DocID:                 getString(chapter, "_docID"),
			EntryID:               getString(chapter, "entry_id"),
			Title:                 getString(chapter, "title"),
			StartPage:             getInt(chapter, "start_page"),
			SortOrder:             getInt(chapter, "sort_order"),
			AudioInclude:          getBool(chapter, "audio_include"),
			AudioIncludeReasoning: getString(chapter, "audio_include_reasoning"),
		})
	}
	if len(chapters) == 0 {
		writeError(w, http.StatusConflict, "book has no structured chapters to repair")
		return
	}
	sort.Slice(chapters, func(i, j int) bool {
		return chapters[i].SortOrder < chapters[j].SortOrder
	})
	includedBefore := make(map[string]bool, len(chapters))
	for _, chapter := range chapters {
		includedBefore[chapter.DocID] = chapter.AudioInclude
	}
	common.CoalesceSharedStartPageAudio(chapters)

	entries := make([]RepairSamePageAudioEntry, 0)
	for _, chapter := range chapters {
		if chapter.DocID == "" || !includedBefore[chapter.DocID] || chapter.AudioInclude {
			continue
		}
		result, err := client.UpdateWithVersion(r.Context(), "Chapter", chapter.DocID, map[string]any{
			"audio_include":           false,
			"audio_include_reasoning": chapter.AudioIncludeReasoning,
		})
		if err != nil {
			writeError(w, http.StatusInternalServerError,
				fmt.Sprintf("same-page audio repair stopped after %d update(s): %v", len(entries), err))
			return
		}
		entries = append(entries, RepairSamePageAudioEntry{
			ChapterID: chapter.DocID,
			EntryID:   chapter.EntryID,
			Title:     chapter.Title,
			StartPage: chapter.StartPage,
			Reason:    chapter.AudioIncludeReasoning,
			CID:       result.CID,
		})
	}
	status = "unchanged"
	if len(entries) > 0 {
		status = "repaired"
	}
	writeJSON(w, http.StatusOK, RepairSamePageAudioResponse{
		BookID:  bookID,
		Status:  status,
		Changed: len(entries),
		Entries: entries,
	})
}

func (e *RepairSamePageAudioEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "repair-same-page-audio <book_id>",
		Short: "Remove duplicate audio ownership at shared scan-page boundaries",
		Long: `Apply Shelf's deterministic same-page ownership rule to a completed
book without rerunning OCR, ToC, classification, or polish. The command is
idempotent and is intended for upgrading books processed before this rule was
introduced.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			var resp RepairSamePageAudioResponse
			if err := api.NewClient(getServerURL()).Post(
				cmd.Context(),
				"/api/books/"+args[0]+"/repair-same-page-audio",
				struct{}{},
				&resp,
			); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
}
