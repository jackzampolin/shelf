package common

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// TocEntryInsertionSpec describes one source-visible heading that was omitted
// from ToC extraction. The anchor is required so same-page headings retain
// source order instead of depending on database tie ordering.
type TocEntryInsertionSpec struct {
	Title           string
	PageNum         int
	Level           int
	LevelName       string
	AfterEntryDocID string
	Reason          string
}

// TocEntryInsertionResult describes the durable, already-linked TocEntry.
type TocEntryInsertionResult struct {
	TocDocID   string
	EntryDocID string
	Title      string
	SortOrder  int
	PageNum    int
	Level      int
	LevelName  string
	AfterEntry string
	Reason     string
	CID        string
}

type validatedTocEntryInsertion struct {
	spec      TocEntryInsertionSpec
	tocDocID  string
	pageDocID string
	uniqueKey string
	anchor    *LinkedTocEntry
}

// ValidateTocEntryInsertion checks source order, the target page, and durable
// identity before an endpoint interrupts active work.
func ValidateTocEntryInsertion(ctx context.Context, book *BookState, spec TocEntryInsertionSpec) error {
	_, err := validateTocEntryInsertion(ctx, book, spec)
	return err
}

func validateTocEntryInsertion(ctx context.Context, book *BookState, spec TocEntryInsertionSpec) (*validatedTocEntryInsertion, error) {
	if book == nil {
		return nil, fmt.Errorf("book state is required")
	}
	spec.Title = strings.TrimSpace(spec.Title)
	spec.LevelName = strings.TrimSpace(spec.LevelName)
	spec.AfterEntryDocID = strings.TrimSpace(spec.AfterEntryDocID)
	spec.Reason = strings.TrimSpace(spec.Reason)
	if spec.Title == "" {
		return nil, fmt.Errorf("title is required")
	}
	if spec.Reason == "" {
		return nil, fmt.Errorf("source-backed reason is required")
	}
	if spec.Level < 1 || spec.Level > 8 {
		return nil, fmt.Errorf("level must be between 1 and 8")
	}
	if spec.LevelName == "" {
		return nil, fmt.Errorf("level name is required")
	}
	if err := defra.ValidateID(spec.AfterEntryDocID); err != nil {
		return nil, fmt.Errorf("invalid anchor ToC entry ID: %w", err)
	}
	tocDocID := book.TocDocID()
	if tocDocID == "" {
		return nil, fmt.Errorf("book has no ToC record")
	}
	if spec.PageNum < 1 || spec.PageNum > book.TotalPages {
		return nil, fmt.Errorf("page %d is outside valid range 1-%d", spec.PageNum, book.TotalPages)
	}
	page := book.GetPage(spec.PageNum)
	if page == nil {
		return nil, fmt.Errorf("page %d is missing", spec.PageNum)
	}
	if quarantined, reason := page.OCRQuarantine(); quarantined {
		return nil, fmt.Errorf("page %d is OCR-quarantined: %s", spec.PageNum, reason)
	}
	if !page.OcrResolved(book.OcrProviders) {
		return nil, fmt.Errorf("page %d does not have terminal OCR", spec.PageNum)
	}
	pageDocID := page.GetPageDocID()
	if pageDocID == "" {
		return nil, fmt.Errorf("page %d has no durable document ID", spec.PageNum)
	}

	linked, records, err := loadInsertionEntries(ctx, book, tocDocID)
	if err != nil {
		return nil, err
	}
	var anchor *LinkedTocEntry
	for _, entry := range linked {
		if entry.DocID == spec.AfterEntryDocID {
			anchor = entry
			break
		}
	}
	if anchor == nil || anchor.ActualPage == nil {
		return nil, fmt.Errorf("anchor ToC entry %s is not a linked entry in this book", spec.AfterEntryDocID)
	}

	uniqueKey := operatorInsertionUniqueKey(tocDocID, spec)
	existingDoc := ""
	for _, record := range records {
		docID, _ := record["_docID"].(string)
		key, _ := record["unique_key"].(string)
		if key == uniqueKey {
			existingDoc = docID
			continue
		}
		title, _ := record["title"].(string)
		linkedPageID, _ := record["_actual_pageID"].(string)
		if strings.EqualFold(strings.TrimSpace(title), spec.Title) && linkedPageID == pageDocID {
			return nil, fmt.Errorf("ToC entry %q is already linked to page %d as %s", spec.Title, spec.PageNum, docID)
		}
	}

	ordered := make([]*LinkedTocEntry, 0, len(linked))
	for _, entry := range linked {
		if entry.DocID != existingDoc {
			ordered = append(ordered, entry)
		}
	}
	sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].SortOrder < ordered[j].SortOrder })
	anchorIndex := -1
	for i, entry := range ordered {
		if entry.DocID == spec.AfterEntryDocID {
			anchorIndex = i
			break
		}
	}
	if anchorIndex < 0 {
		return nil, fmt.Errorf("anchor ToC entry %s disappeared while validating order", spec.AfterEntryDocID)
	}
	if spec.PageNum < *ordered[anchorIndex].ActualPage {
		return nil, fmt.Errorf("page %d precedes anchor page %d", spec.PageNum, *ordered[anchorIndex].ActualPage)
	}
	if anchorIndex+1 < len(ordered) && ordered[anchorIndex+1].ActualPage != nil && spec.PageNum > *ordered[anchorIndex+1].ActualPage {
		return nil, fmt.Errorf("page %d follows next source entry page %d; choose the correct anchor", spec.PageNum, *ordered[anchorIndex+1].ActualPage)
	}

	return &validatedTocEntryInsertion{
		spec: spec, tocDocID: tocDocID, pageDocID: pageDocID,
		uniqueKey: uniqueKey, anchor: anchor,
	}, nil
}

// InsertTocEntry adds and directly links a source-verified missing entry,
// preserves all existing links, deterministically reorders same-page entries,
// and invalidates finalize/structure artifacts. Replaying the same request is
// idempotent and resumes the ordering step if an earlier attempt was interrupted.
func InsertTocEntry(ctx context.Context, book *BookState, spec TocEntryInsertionSpec) (*TocEntryInsertionResult, error) {
	target, err := validateTocEntryInsertion(ctx, book, spec)
	if err != nil {
		return nil, err
	}
	if err := ResetFrom(ctx, book, target.tocDocID, ResetTocFinalize); err != nil {
		return nil, fmt.Errorf("reset downstream of ToC entry insertion: %w", err)
	}

	store := book.getStore(ctx)
	timestamp := time.Now().UTC().Format(time.RFC3339)
	doc := map[string]any{
		"_tocID":             target.tocDocID,
		"unique_key":         target.uniqueKey,
		"title":              target.spec.Title,
		"level":              target.spec.Level,
		"level_name":         target.spec.LevelName,
		"sort_order":         target.anchor.SortOrder,
		"source":             "operator",
		"_actual_pageID":     target.pageDocID,
		"link_repair_reason": target.spec.Reason,
		"link_repaired_at":   timestamp,
		"link_retries":       0,
		"link_failed":        false,
		"link_excluded":      false,
	}
	writeResult, err := store.UpsertWithVersion(ctx, "TocEntry", map[string]any{"unique_key": target.uniqueKey}, doc, doc)
	if err != nil {
		return nil, fmt.Errorf("persist inserted ToC entry: %w", err)
	}

	// Re-load after the upsert so a replay and a fresh insertion follow the
	// same path, then place the entry immediately after its explicit anchor.
	linked, records, err := loadInsertionEntries(ctx, book, target.tocDocID)
	if err != nil {
		return nil, fmt.Errorf("reload ToC entries after insertion: %w", err)
	}
	var inserted *LinkedTocEntry
	for _, entry := range linked {
		if entry.DocID == writeResult.DocID {
			inserted = entry
		}
	}
	if inserted == nil {
		return nil, fmt.Errorf("inserted ToC entry %s was not reloadable", writeResult.DocID)
	}
	finalOrder, orderedLinked, err := persistTocInsertionOrder(ctx, store, records, linked, writeResult.DocID, target.spec.AfterEntryDocID)
	if err != nil {
		return nil, fmt.Errorf("persist inserted ToC entry order: %w", err)
	}
	book.SetLinkedEntries(orderedLinked)

	book.SetTocEntries(nil)
	book.SetTocLinkProgress(0, 0)
	book.SetOpState(OpTocLink, false, true, false, 0)
	if err := book.PersistOpState(ctx, OpTocLink); err != nil {
		return nil, fmt.Errorf("persist complete ToC link state: %w", err)
	}
	if err := book.PersistTocLinkProgress(ctx); err != nil {
		return nil, fmt.Errorf("persist ToC link progress: %w", err)
	}

	return &TocEntryInsertionResult{
		TocDocID: target.tocDocID, EntryDocID: writeResult.DocID,
		Title: target.spec.Title, SortOrder: finalOrder, PageNum: target.spec.PageNum,
		Level: target.spec.Level, LevelName: target.spec.LevelName,
		AfterEntry: target.spec.AfterEntryDocID, Reason: target.spec.Reason, CID: writeResult.CID,
	}, nil
}

func persistTocInsertionOrder(ctx context.Context, store StateStore, records []map[string]any, linked []*LinkedTocEntry, insertedDocID, anchorDocID string) (int, []*LinkedTocEntry, error) {
	sort.SliceStable(records, func(i, j int) bool {
		left, right := numericToInt(records[i]["sort_order"]), numericToInt(records[j]["sort_order"])
		if left == right {
			return numericString(records[i]["_docID"]) < numericString(records[j]["_docID"])
		}
		return left < right
	})
	var inserted map[string]any
	withoutInserted := make([]map[string]any, 0, len(records))
	for _, record := range records {
		if numericString(record["_docID"]) == insertedDocID {
			inserted = record
			continue
		}
		withoutInserted = append(withoutInserted, record)
	}
	if inserted == nil {
		return 0, nil, fmt.Errorf("inserted ToC entry %s is absent from ordering records", insertedDocID)
	}
	ordered := make([]map[string]any, 0, len(records))
	foundAnchor := false
	for _, record := range withoutInserted {
		ordered = append(ordered, record)
		if numericString(record["_docID"]) == anchorDocID {
			ordered = append(ordered, inserted)
			foundAnchor = true
		}
	}
	if !foundAnchor {
		return 0, nil, fmt.Errorf("anchor ToC entry %s disappeared during insertion", anchorDocID)
	}

	var ops []defra.WriteOp
	finalOrderByDocID := make(map[string]int, len(ordered))
	for newOrder, record := range ordered {
		docID := numericString(record["_docID"])
		finalOrderByDocID[docID] = newOrder
		if numericToInt(record["sort_order"]) == newOrder {
			continue
		}
		ops = append(ops, defra.WriteOp{
			Collection: "TocEntry", DocID: docID,
			Document: map[string]any{"sort_order": newOrder}, Op: defra.OpUpdate,
		})
	}
	if len(ops) > 0 {
		results, err := store.SendManySync(ctx, ops)
		if err != nil {
			return 0, nil, err
		}
		for i, result := range results {
			if result.Err != nil {
				return 0, nil, fmt.Errorf("update ToC entry %s sort order: %w", ops[i].DocID, result.Err)
			}
		}
	}
	for _, entry := range linked {
		entry.SortOrder = finalOrderByDocID[entry.DocID]
	}
	sort.SliceStable(linked, func(i, j int) bool { return linked[i].SortOrder < linked[j].SortOrder })
	return finalOrderByDocID[insertedDocID], linked, nil
}

func operatorInsertionUniqueKey(tocDocID string, spec TocEntryInsertionSpec) string {
	sum := sha256.Sum256([]byte(strings.ToLower(strings.TrimSpace(spec.Title)) + "\x00" + fmt.Sprint(spec.PageNum) + "\x00" + strings.TrimSpace(spec.AfterEntryDocID)))
	return fmt.Sprintf("%s:operator:%s", tocDocID, hex.EncodeToString(sum[:12]))
}

func loadInsertionEntries(ctx context.Context, book *BookState, tocDocID string) ([]*LinkedTocEntry, []map[string]any, error) {
	store := book.getStore(ctx)
	if store == nil {
		return nil, nil, fmt.Errorf("no store available")
	}
	query := fmt.Sprintf(`{
		TocEntry(filter: {_tocID: {_eq: %q}}) {
			_docID
			unique_key
			title
			entry_number
			level
			level_name
			printed_page_number
			sort_order
			source
			link_excluded
			_actual_pageID
		}
	}`, tocDocID)
	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return nil, nil, fmt.Errorf("query ToC entries for insertion: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, nil, fmt.Errorf("query ToC entries for insertion: %s", errMsg)
	}
	raw, _ := resp.Data["TocEntry"].([]any)
	pageNumByDocID := make(map[string]int, book.TotalPages)
	for pageNum := 1; pageNum <= book.TotalPages; pageNum++ {
		if page := book.GetPage(pageNum); page != nil && page.GetPageDocID() != "" {
			pageNumByDocID[page.GetPageDocID()] = pageNum
		}
	}
	records := make([]map[string]any, 0, len(raw))
	linked := make([]*LinkedTocEntry, 0, len(raw))
	for _, item := range raw {
		record, ok := item.(map[string]any)
		if !ok {
			continue
		}
		records = append(records, record)
		if excluded, _ := record["link_excluded"].(bool); excluded {
			continue
		}
		pageDocID, _ := record["_actual_pageID"].(string)
		pageNum, ok := pageNumByDocID[pageDocID]
		if !ok {
			continue
		}
		entry := &LinkedTocEntry{
			DocID: numericString(record["_docID"]), Title: numericString(record["title"]),
			EntryNumber: numericString(record["entry_number"]), Level: numericToInt(record["level"]),
			LevelName: numericString(record["level_name"]), SortOrder: numericToInt(record["sort_order"]),
			ActualPage: &pageNum, ActualPageDocID: pageDocID,
			PrintedPageNumber: numericString(record["printed_page_number"]), Source: numericString(record["source"]),
		}
		if entry.DocID != "" {
			linked = append(linked, entry)
		}
	}
	sort.SliceStable(linked, func(i, j int) bool { return linked[i].SortOrder < linked[j].SortOrder })
	return linked, records, nil
}

func numericString(v any) string {
	s, _ := v.(string)
	return s
}
