package common

import (
	"context"
	"fmt"
	"sort"

	"github.com/jackzampolin/shelf/internal/defra"
)

// OCRRepairResult describes the durable changes made by RepairOCRPages.
type OCRRepairResult struct {
	Pages          []int
	Providers      []string
	DeletedResults int
}

// RepairOCRPages selectively removes persisted OCR results and marks the
// requested pages incomplete. It does not reset downstream operations or start
// a job; callers must do both after this succeeds so repaired text is propagated
// into metadata, ToC links, and structure.
//
// All reads are completed before writes begin. Database writes are synchronous,
// and in-memory state is changed only after every write succeeds. The operation
// is idempotent: retrying after a partial external failure safely converges.
func RepairOCRPages(ctx context.Context, book *BookState, pageNums []int, providers []string) (*OCRRepairResult, error) {
	if book == nil {
		return nil, fmt.Errorf("book is required")
	}
	if book.Store == nil {
		return nil, fmt.Errorf("book state store is required")
	}

	pages, err := normalizeRepairPages(pageNums, book.TotalPages)
	if err != nil {
		return nil, err
	}
	repairProviders, err := normalizeRepairProviders(providers, book.OcrProviders)
	if err != nil {
		return nil, err
	}
	providerSet := make(map[string]struct{}, len(repairProviders))
	for _, provider := range repairProviders {
		providerSet[provider] = struct{}{}
	}

	type repairPage struct {
		pageNum int
		state   *PageState
		docID   string
	}
	targets := make([]repairPage, 0, len(pages))
	deleteOps := make([]defra.WriteOp, 0, len(pages)*len(repairProviders))

	for _, pageNum := range pages {
		state := book.GetPage(pageNum)
		if state == nil {
			return nil, fmt.Errorf("page %d is not present in durable book state", pageNum)
		}
		pageDocID := state.GetPageDocID()
		if pageDocID == "" {
			return nil, fmt.Errorf("page %d has no durable document ID", pageNum)
		}

		query := fmt.Sprintf(`{
			OcrResult(filter: {_pageID: {_eq: "%s"}}) {
				_docID
				provider
			}
		}`, pageDocID)
		resp, err := book.Store.Execute(ctx, query, nil)
		if err != nil {
			return nil, fmt.Errorf("query OCR results for page %d: %w", pageNum, err)
		}
		if errMsg := resp.Error(); errMsg != "" {
			return nil, fmt.Errorf("query OCR results for page %d: %s", pageNum, errMsg)
		}
		if results, ok := resp.Data["OcrResult"].([]any); ok {
			for _, raw := range results {
				result, ok := raw.(map[string]any)
				if !ok {
					continue
				}
				provider, _ := result["provider"].(string)
				if _, repair := providerSet[provider]; !repair {
					continue
				}
				docID, _ := result["_docID"].(string)
				if docID == "" {
					return nil, fmt.Errorf("OCR result for page %d provider %s has no document ID", pageNum, provider)
				}
				deleteOps = append(deleteOps, defra.WriteOp{
					Collection: "OcrResult",
					DocID:      docID,
					Op:         defra.OpDelete,
					Source:     "RepairOCRPages:delete_result",
				})
			}
		}
		targets = append(targets, repairPage{pageNum: pageNum, state: state, docID: pageDocID})
	}

	ops := make([]defra.WriteOp, 0, len(deleteOps)+len(targets))
	ops = append(ops, deleteOps...)
	for _, target := range targets {
		ops = append(ops, defra.WriteOp{
			Collection: "Page",
			DocID:      target.docID,
			Document: map[string]any{
				"ocr_complete": false,
				"ocr_markdown": nil,
				"headings":     nil,
				"header":       nil,
				"footer":       nil,
			},
			Op:     defra.OpUpdate,
			Source: "RepairOCRPages:reset_page",
		})
	}

	results, err := book.Store.SendManySync(ctx, ops)
	if err != nil {
		return nil, fmt.Errorf("persist OCR page repair: %w", err)
	}
	for i, result := range results {
		if result.Err != nil {
			return nil, fmt.Errorf("persist OCR page repair operation %d for %s: %w", i, result.DocID, result.Err)
		}
	}

	for _, target := range targets {
		target.state.ResetOcrProviders(repairProviders)
	}

	return &OCRRepairResult{
		Pages:          pages,
		Providers:      repairProviders,
		DeletedResults: len(deleteOps),
	}, nil
}

func normalizeRepairPages(pageNums []int, totalPages int) ([]int, error) {
	if len(pageNums) == 0 {
		return nil, fmt.Errorf("at least one page is required")
	}
	seen := make(map[int]struct{}, len(pageNums))
	pages := make([]int, 0, len(pageNums))
	for _, pageNum := range pageNums {
		if pageNum < 1 || pageNum > totalPages {
			return nil, fmt.Errorf("page %d is outside valid range 1-%d", pageNum, totalPages)
		}
		if _, ok := seen[pageNum]; ok {
			continue
		}
		seen[pageNum] = struct{}{}
		pages = append(pages, pageNum)
	}
	sort.Ints(pages)
	return pages, nil
}

func normalizeRepairProviders(providers, configured []string) ([]string, error) {
	if len(providers) == 0 {
		return nil, fmt.Errorf("at least one OCR provider is required")
	}
	configuredSet := make(map[string]struct{}, len(configured))
	for _, provider := range configured {
		configuredSet[provider] = struct{}{}
	}
	seen := make(map[string]struct{}, len(providers))
	result := make([]string, 0, len(providers))
	for _, provider := range providers {
		if _, ok := configuredSet[provider]; !ok {
			return nil, fmt.Errorf("OCR provider %q is not configured for this book", provider)
		}
		if _, ok := seen[provider]; ok {
			continue
		}
		seen[provider] = struct{}{}
		result = append(result, provider)
	}
	sort.Strings(result)
	return result, nil
}
