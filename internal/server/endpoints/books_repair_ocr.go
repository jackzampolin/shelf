package endpoints

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
	"strconv"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobcfg"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// RepairOCRRequest selects exact pages and OCR providers to repair.
type RepairOCRRequest struct {
	Pages     []int    `json:"pages"`
	Providers []string `json:"providers,omitempty"` // Defaults to configured OCR providers.
	Force     bool     `json:"force,omitempty"`     // Cancel an active process-book job first.
	Variant   string   `json:"variant,omitempty"`   // Optional process-book pipeline variant.
}

// RepairOCRResponse reports the selective reset and replacement job.
type RepairOCRResponse struct {
	BookID         string   `json:"book_id"`
	Pages          []int    `json:"pages"`
	Providers      []string `json:"providers"`
	DeletedResults int      `json:"deleted_results"`
	JobID          string   `json:"job_id"`
	Status         string   `json:"status"`
}

// RepairOCREndpoint handles POST /api/books/{book_id}/repair-ocr.
type RepairOCREndpoint struct{}

func (e *RepairOCREndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/{book_id}/repair-ocr", e.handler
}

func (e *RepairOCREndpoint) RequiresInit() bool { return true }

func (e *RepairOCREndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	var req RepairOCRRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if len(req.Pages) == 0 {
		writeError(w, http.StatusBadRequest, "at least one page is required")
		return
	}
	for _, pageNum := range req.Pages {
		if pageNum < 1 {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("page %d must be positive", pageNum))
			return
		}
	}

	scheduler := svcctx.SchedulerFrom(r.Context())
	if scheduler == nil {
		writeError(w, http.StatusServiceUnavailable, "scheduler not initialized")
		return
	}
	configStore := svcctx.ConfigStoreFrom(r.Context())
	if configStore == nil {
		writeError(w, http.StatusServiceUnavailable, "config store not initialized")
		return
	}

	builder := jobcfg.NewBuilder(configStore)
	cfg, err := builder.ProcessBookConfig(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to load config: %v", err))
		return
	}
	if req.Variant != "" {
		variant := process_book.PipelineVariant(req.Variant)
		if !variant.IsValid() {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid variant: %s (valid variants: standard, photo-book, text-only, ocr-only)", req.Variant))
			return
		}
		cfg.ApplyVariant(variant)
	}

	providers := req.Providers
	if len(providers) == 0 {
		providers = append([]string(nil), cfg.OcrProviders...)
	}
	if err := validateRepairProviders(providers, cfg.OcrProviders); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	pageCount, err := repairBookPageCount(r.Context(), bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to read book: %v", err))
		return
	}
	if pageCount == 0 {
		writeError(w, http.StatusNotFound, "book not found or has no pages")
		return
	}
	for _, pageNum := range req.Pages {
		if pageNum > pageCount {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("page %d is outside valid range 1-%d", pageNum, pageCount))
			return
		}
	}

	if httpStatus, err := prepareBookJobStart(r.Context(), scheduler, bookID, process_book.JobType, req.Force); err != nil {
		writeError(w, httpStatus, err.Error())
		return
	}

	job, err := process_book.NewJob(r.Context(), cfg, bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create repair job: %v", err))
		return
	}
	jobContext, ok := job.(common.JobContext)
	if !ok {
		writeError(w, http.StatusInternalServerError, "process-book job does not expose book state")
		return
	}
	book := jobContext.GetBook()
	repair, err := common.RepairOCRPages(r.Context(), book, req.Pages, providers)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to repair OCR pages: %v", err))
		return
	}
	if err := resetRepairDownstream(r.Context(), book, cfg); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to invalidate downstream state: %v", err))
		return
	}

	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit repair job: %v", err))
		return
	}

	writeJSON(w, http.StatusAccepted, RepairOCRResponse{
		BookID:         bookID,
		Pages:          repair.Pages,
		Providers:      repair.Providers,
		DeletedResults: repair.DeletedResults,
		JobID:          job.ID(),
		Status:         "queued",
	})
}

func repairBookPageCount(ctx context.Context, bookID string) (int, error) {
	if err := defra.ValidateID(bookID); err != nil {
		return 0, fmt.Errorf("invalid book ID: %w", err)
	}
	client := svcctx.DefraClientFrom(ctx)
	if client == nil {
		return 0, fmt.Errorf("defra client not initialized")
	}
	query := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			page_count
		}
	}`, bookID)
	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		return 0, err
	}
	if errMsg := resp.Error(); errMsg != "" {
		return 0, fmt.Errorf("query error: %s", errMsg)
	}
	books, ok := resp.Data["Book"].([]any)
	if !ok || len(books) == 0 {
		return 0, nil
	}
	book, ok := books[0].(map[string]any)
	if !ok {
		return 0, fmt.Errorf("unexpected book response type %T", books[0])
	}
	pageCount, _ := book["page_count"].(float64)
	return int(pageCount), nil
}

func resetRepairDownstream(ctx context.Context, book *common.BookState, cfg process_book.Config) error {
	if cfg.EnableMetadata {
		if err := common.ResetFrom(ctx, book, book.TocDocID(), common.ResetMetadata); err != nil {
			return fmt.Errorf("metadata: %w", err)
		}
	}
	if cfg.EnableTocFinder || cfg.EnableTocExtract || cfg.EnableTocLink || cfg.EnableTocFinalize || cfg.EnableStructure {
		if err := common.ResetFrom(ctx, book, book.TocDocID(), common.ResetTocFinder); err != nil {
			return fmt.Errorf("toc_finder: %w", err)
		}
	}
	return nil
}

func validateRepairProviders(providers, configured []string) error {
	if len(providers) == 0 {
		return fmt.Errorf("at least one OCR provider is required")
	}
	configuredSet := make(map[string]struct{}, len(configured))
	for _, provider := range configured {
		configuredSet[provider] = struct{}{}
	}
	for _, provider := range providers {
		if _, ok := configuredSet[provider]; !ok {
			return fmt.Errorf("OCR provider %q is not configured", provider)
		}
	}
	return nil
}

func (e *RepairOCREndpoint) Command(getServerURL func() string) *cobra.Command {
	var pageSpec string
	var providers []string
	var force bool
	var variant string
	cmd := &cobra.Command{
		Use:   "repair-ocr <book_id>",
		Short: "Repair OCR for selected pages and restart processing",
		Long: `Delete selected persisted OCR results, mark only those pages incomplete,
invalidate metadata and downstream ToC/structure state, and immediately submit a
replacement process-book job. Page specifications accept commas and ranges,
for example: --pages 9,17,19,21,26-28.

Use --force when the book already has an active process-book job.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			pages, err := parsePageSpec(pageSpec)
			if err != nil {
				return err
			}
			client := api.NewClient(getServerURL())
			var resp RepairOCRResponse
			if err := client.Post(cmd.Context(), "/api/books/"+args[0]+"/repair-ocr", RepairOCRRequest{
				Pages:     pages,
				Providers: providers,
				Force:     force,
				Variant:   variant,
			}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&pageSpec, "pages", "", "Pages to repair (comma-separated numbers and ranges)")
	cmd.Flags().StringSliceVar(&providers, "provider", nil, "OCR provider(s) to repair; defaults to configured providers")
	cmd.Flags().BoolVar(&force, "force", false, "Cancel an active process-book job before repair")
	cmd.Flags().StringVar(&variant, "variant", "", "Pipeline variant (standard, photo-book, text-only, ocr-only)")
	_ = cmd.MarkFlagRequired("pages")
	return cmd
}

func parsePageSpec(spec string) ([]int, error) {
	seen := make(map[int]struct{})
	var pages []int
	for _, token := range strings.Split(spec, ",") {
		token = strings.TrimSpace(token)
		if token == "" {
			continue
		}
		parts := strings.Split(token, "-")
		if len(parts) > 2 {
			return nil, fmt.Errorf("invalid page range %q", token)
		}
		start, err := strconv.Atoi(strings.TrimSpace(parts[0]))
		if err != nil || start < 1 {
			return nil, fmt.Errorf("invalid page %q", token)
		}
		end := start
		if len(parts) == 2 {
			end, err = strconv.Atoi(strings.TrimSpace(parts[1]))
			if err != nil || end < start {
				return nil, fmt.Errorf("invalid page range %q", token)
			}
		}
		for pageNum := start; pageNum <= end; pageNum++ {
			if _, ok := seen[pageNum]; ok {
				continue
			}
			seen[pageNum] = struct{}{}
			pages = append(pages, pageNum)
		}
	}
	if len(pages) == 0 {
		return nil, fmt.Errorf("at least one page is required")
	}
	sort.Ints(pages)
	return pages, nil
}
