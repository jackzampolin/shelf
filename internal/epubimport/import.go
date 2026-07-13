package epubimport

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
)

const createBatchSize = 25

// SourceError identifies an invalid, unreadable, or unsupported caller source.
// Other errors are server-side persistence failures.
type SourceError struct{ Err error }

func (e *SourceError) Error() string { return e.Err.Error() }
func (e *SourceError) Unwrap() error { return e.Err }

// IsSourceError reports whether an import failure is attributable to the input.
func IsSourceError(err error) bool {
	var sourceErr *SourceError
	return errors.As(err, &sourceErr)
}

// Options are explicit operator overrides for package metadata.
type Options struct {
	Title  string
	Author string
}

// Result describes a terminal direct import.
type Result struct {
	BookID            string `json:"book_id"`
	Title             string `json:"title"`
	Author            string `json:"author,omitempty"`
	Status            string `json:"status"`
	SourceFormat      string `json:"source_format"`
	SourceSHA256      string `json:"source_sha256"`
	SourcePath        string `json:"source_path"`
	Chapters          int    `json:"chapters"`
	Paragraphs        int    `json:"paragraphs"`
	Words             int    `json:"words"`
	Duplicate         bool   `json:"duplicate"`
	sourceFilename    string
	structureComplete bool
}

// Import parses an EPUB completely, deduplicates it by source hash, and writes
// a terminal structured Shelf book. Parsing is a preflight: no database or
// filesystem mutation occurs until the full package/spine is usable.
func Import(ctx context.Context, client *defra.Client, homeDir *home.Dir, filename string, opts Options) (*Result, error) {
	if client == nil {
		return nil, fmt.Errorf("defra client is required")
	}
	if homeDir == nil {
		return nil, fmt.Errorf("shelf home is required")
	}
	abs, err := filepath.Abs(filename)
	if err != nil {
		return nil, &SourceError{Err: fmt.Errorf("resolve EPUB path: %w", err)}
	}
	info, err := os.Stat(abs)
	if err != nil {
		return nil, &SourceError{Err: fmt.Errorf("stat EPUB: %w", err)}
	}
	if !info.Mode().IsRegular() {
		return nil, &SourceError{Err: fmt.Errorf("EPUB path is not a regular file: %s", abs)}
	}
	if !strings.EqualFold(filepath.Ext(abs), ".epub") {
		return nil, &SourceError{Err: fmt.Errorf("source is not an .epub file: %s", abs)}
	}

	hash, err := fileSHA256(abs)
	if err != nil {
		return nil, &SourceError{Err: err}
	}
	publication, err := Parse(abs)
	if err != nil {
		return nil, &SourceError{Err: err}
	}
	if title := strings.TrimSpace(opts.Title); title != "" {
		publication.Title = title
	}
	if author := strings.TrimSpace(opts.Author); author != "" {
		publication.Authors = []string{author}
	}

	if existing, err := findExisting(ctx, client, hash); err != nil {
		return nil, err
	} else if existing != nil {
		if existing.Status == "complete" && existing.structureComplete && existing.Chapters > 0 {
			existing.SourcePath = filepath.Join(homeDir.OriginalsDir(existing.BookID), existing.sourceFilename)
			existing.Duplicate = true
			return existing, nil
		}
		if err := purgeIncompleteImport(ctx, client, homeDir, existing.BookID); err != nil {
			return nil, fmt.Errorf("recover incomplete EPUB import %s: %w", existing.BookID, err)
		}
	}

	now := time.Now().UTC().Format(time.RFC3339Nano)
	author := ""
	if len(publication.Authors) > 0 {
		author = publication.Authors[0]
	}
	bookInput := map[string]any{
		"title":              publication.Title,
		"author":             author,
		"authors":            publication.Authors,
		"language":           publication.Language,
		"publisher":          nilIfEmpty(publication.Publisher),
		"description":        nilIfEmpty(publication.Description),
		"subjects":           publication.Subjects,
		"page_count":         len(publication.Chapters),
		"status":             "processing",
		"created_at":         now,
		"metadata_started":   false,
		"metadata_complete":  true,
		"metadata_failed":    false,
		"metadata_retries":   0,
		"structure_started":  true,
		"structure_complete": false,
		"structure_failed":   false,
		"structure_retries":  0,
		"structure_phase":    "direct_epub_import",
		"source_format":      "epub",
		"source_filename":    filepath.Base(abs),
		"source_sha256":      hash,
		"source_identifier":  nilIfEmpty(publication.Identifier),
		"source_imported_at": now,
	}
	bookID, err := client.Create(ctx, "Book", bookInput)
	if err != nil {
		return nil, fmt.Errorf("create EPUB Book record: %w", err)
	}

	created := map[string][]string{"Book": {bookID}}
	rollback := func(cause error) error {
		for _, collection := range []string{"OcrResult", "Paragraph", "Chapter", "TocEntry", "Page", "ToC", "Book"} {
			ids := created[collection]
			for i := len(ids) - 1; i >= 0; i-- {
				_ = client.Delete(context.Background(), collection, ids[i])
			}
		}
		_ = os.RemoveAll(homeDir.SourceImagesDir(bookID))
		return cause
	}

	if err := homeDir.EnsureOriginalsDir(bookID); err != nil {
		return nil, rollback(fmt.Errorf("create EPUB originals directory: %w", err))
	}
	destPath := filepath.Join(homeDir.OriginalsDir(bookID), filepath.Base(abs))
	if err := copySource(abs, destPath); err != nil {
		return nil, rollback(fmt.Errorf("preserve source EPUB: %w", err))
	}

	pageInputs := make([]map[string]any, 0, len(publication.Chapters))
	for i, chapter := range publication.Chapters {
		pageInputs = append(pageInputs, map[string]any{
			"_bookID":          bookID,
			"page_num":         i + 1,
			"ocr_markdown":     chapter.Markdown,
			"headings":         "[]",
			"extract_complete": true,
			"ocr_complete":     true,
			"ocr_quarantined":  false,
		})
	}
	pageResults, err := createManyBatched(ctx, client, "Page", pageInputs, "page_num")
	for _, result := range pageResults {
		created["Page"] = append(created["Page"], result.DocID)
	}
	if err != nil {
		return nil, rollback(fmt.Errorf("create EPUB logical pages: %w", err))
	}
	pageIDs := make(map[int]string, len(pageResults))
	for _, result := range pageResults {
		pageIDs[numberField(result.Fields["page_num"])] = result.DocID
	}

	tocID, err := client.Create(ctx, "ToC", map[string]any{
		"created_at":        now,
		"toc_found":         true,
		"start_page":        1,
		"end_page":          len(publication.Chapters),
		"structure_summary": map[string]any{"source": "epub_navigation", "entries": len(publication.Chapters)},
		"finder_started":    false,
		"finder_complete":   true,
		"finder_failed":     false,
		"finder_retries":    0,
		"extract_started":   false,
		"extract_complete":  true,
		"extract_failed":    false,
		"extract_retries":   0,
		"link_started":      false,
		"link_complete":     true,
		"link_failed":       false,
		"link_retries":      0,
		"finalize_started":  false,
		"finalize_complete": true,
		"finalize_failed":   false,
		"finalize_retries":  0,
		"finalize_phase":    "done",
	})
	if err != nil {
		return nil, rollback(fmt.Errorf("create EPUB navigation record: %w", err))
	}
	created["ToC"] = append(created["ToC"], tocID)
	if err := client.Update(ctx, "Book", bookID, map[string]any{"_tocID": tocID}); err != nil {
		return nil, rollback(fmt.Errorf("link EPUB navigation to Book: %w", err))
	}
	tocEntryInputs := make([]map[string]any, 0, len(publication.Chapters))
	for i, chapter := range publication.Chapters {
		tocEntryInputs = append(tocEntryInputs, map[string]any{
			"_tocID":         tocID,
			"unique_key":     fmt.Sprintf("%s:epub:%03d", tocID, i+1),
			"entry_number":   fmt.Sprintf("%d", i+1),
			"title":          chapter.Title,
			"level":          chapter.Level,
			"level_name":     levelName(chapter.Level),
			"_actual_pageID": pageIDs[i+1],
			"source":         "epub_navigation",
			"sort_order":     (i + 1) * 100,
		})
	}
	tocEntryResults, err := createManyBatched(ctx, client, "TocEntry", tocEntryInputs, "entry_number")
	for _, result := range tocEntryResults {
		created["TocEntry"] = append(created["TocEntry"], result.DocID)
	}
	if err != nil {
		return nil, rollback(fmt.Errorf("create EPUB navigation entries: %w", err))
	}
	tocEntryIDs := make(map[string]string, len(tocEntryResults))
	for _, result := range tocEntryResults {
		tocEntryIDs[stringField(result.Fields["entry_number"])] = result.DocID
	}

	ocrInputs := make([]map[string]any, 0, len(publication.Chapters))
	for i, chapter := range publication.Chapters {
		ocrInputs = append(ocrInputs, map[string]any{
			"_pageID":    pageIDs[i+1],
			"provider":   "epub",
			"text":       chapter.Markdown,
			"confidence": 1.0,
			"provider_metadata": map[string]any{
				"source": "epub_spine", "href": chapter.SourceHref,
			},
			"created_at": now,
		})
	}
	ocrResults, err := createManyBatched(ctx, client, "OcrResult", ocrInputs)
	for _, result := range ocrResults {
		created["OcrResult"] = append(created["OcrResult"], result.DocID)
	}
	if err != nil {
		return nil, rollback(fmt.Errorf("create EPUB provenance rows: %w", err))
	}

	chapterInputs := make([]map[string]any, 0, len(publication.Chapters))
	parentByLevel := make(map[int]string)
	totalWords := 0
	totalParagraphs := 0
	for i, chapter := range publication.Chapters {
		entryID := fmt.Sprintf("epub_%03d", i+1)
		parentID := ""
		if chapter.Level > 1 {
			parentID = parentByLevel[chapter.Level-1]
		}
		parentByLevel[chapter.Level] = entryID
		for level := chapter.Level + 1; level <= 12; level++ {
			delete(parentByLevel, level)
		}
		words := wordCount(chapter.Markdown)
		totalWords += words
		totalParagraphs += len(chapter.Paragraphs)
		chapterInputs = append(chapterInputs, map[string]any{
			"_bookID":                  bookID,
			"_toc_entryID":             tocEntryIDs[fmt.Sprintf("%d", i+1)],
			"unique_key":               fmt.Sprintf("%s:epub:%03d", bookID, i+1),
			"entry_id":                 entryID,
			"sort_order":               (i + 1) * 100,
			"title":                    chapter.Title,
			"level":                    chapter.Level,
			"level_name":               levelName(chapter.Level),
			"entry_number":             fmt.Sprintf("%d", i+1),
			"start_page":               i + 1,
			"end_page":                 i + 1,
			"matter_type":              chapter.MatterType,
			"classification_reasoning": "Derived deterministically from EPUB navigation and title semantics",
			"content_type":             chapter.ContentType,
			"audio_include":            chapter.AudioInclude,
			"audio_include_reasoning":  "Direct EPUB import classification; no OCR or LLM transformation",
			"parent_id":                parentID,
			"source":                   "epub:" + chapter.SourceHref,
			"mechanical_text":          chapter.Markdown,
			"polished_text":            chapter.Markdown,
			"word_count":               words,
			"edits_applied_json":       "[]",
			"extract_complete":         true,
			"polish_complete":          true,
			"polish_failed":            false,
			"polish_retries":           0,
		})
	}
	chapterResults, err := createManyBatched(ctx, client, "Chapter", chapterInputs, "entry_id")
	for _, result := range chapterResults {
		created["Chapter"] = append(created["Chapter"], result.DocID)
	}
	if err != nil {
		return nil, rollback(fmt.Errorf("create EPUB chapters: %w", err))
	}
	chapterIDs := make(map[string]string, len(chapterResults))
	for _, result := range chapterResults {
		chapterIDs[stringField(result.Fields["entry_id"])] = result.DocID
	}

	paragraphInputs := make([]map[string]any, 0, totalParagraphs)
	for i, chapter := range publication.Chapters {
		entryID := fmt.Sprintf("epub_%03d", i+1)
		chapterID := chapterIDs[entryID]
		if chapterID == "" {
			return nil, rollback(fmt.Errorf("EPUB chapter %s has no persisted document ID", entryID))
		}
		for paragraphIndex, paragraph := range chapter.Paragraphs {
			paragraphInputs = append(paragraphInputs, map[string]any{
				"_chapterID":    chapterID,
				"sort_order":    paragraphIndex + 1,
				"start_page":    i + 1,
				"raw_text":      paragraph,
				"polished_text": paragraph,
				"word_count":    wordCount(paragraph),
				"edits_applied": "[]",
			})
		}
	}
	paragraphResults, err := createManyBatched(ctx, client, "Paragraph", paragraphInputs)
	for _, result := range paragraphResults {
		created["Paragraph"] = append(created["Paragraph"], result.DocID)
	}
	if err != nil {
		return nil, rollback(fmt.Errorf("create EPUB paragraphs: %w", err))
	}

	if err := client.Update(ctx, "Book", bookID, map[string]any{
		"status":                       "complete",
		"status_reason":                nil,
		"structure_started":            false,
		"structure_complete":           true,
		"structure_failed":             false,
		"structure_phase":              "complete",
		"structure_chapters_total":     len(publication.Chapters),
		"structure_chapters_extracted": len(publication.Chapters),
		"structure_chapters_polished":  len(publication.Chapters),
		"structure_polish_failed":      0,
		"total_chapters":               len(publication.Chapters),
		"total_paragraphs":             totalParagraphs,
		"total_words":                  totalWords,
	}); err != nil {
		return nil, rollback(fmt.Errorf("certify EPUB import: %w", err))
	}

	return &Result{
		BookID: bookID, Title: publication.Title, Author: author, Status: "complete",
		SourceFormat: "epub", SourceSHA256: hash, SourcePath: destPath,
		Chapters: len(publication.Chapters), Paragraphs: totalParagraphs, Words: totalWords,
	}, nil
}

func findExisting(ctx context.Context, client *defra.Client, hash string) (*Result, error) {
	query := fmt.Sprintf(`{
		Book(filter: {source_sha256: {_eq: %q}}, limit: 2) {
			_docID title author status structure_complete source_format source_filename source_sha256
			total_chapters total_paragraphs total_words
		}
	}`, hash)
	resp, err := client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query existing EPUB hash: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("query existing EPUB hash: %s", errMsg)
	}
	rows, _ := resp.Data["Book"].([]any)
	if len(rows) == 0 {
		return nil, nil
	}
	data, ok := rows[0].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("query existing EPUB hash returned malformed Book")
	}
	return &Result{
		BookID: stringField(data["_docID"]), Title: stringField(data["title"]),
		Author: stringField(data["author"]), Status: stringField(data["status"]),
		SourceFormat: stringField(data["source_format"]), SourceSHA256: stringField(data["source_sha256"]),
		Chapters: numberField(data["total_chapters"]), Paragraphs: numberField(data["total_paragraphs"]),
		Words: numberField(data["total_words"]), sourceFilename: stringField(data["source_filename"]),
		structureComplete: boolField(data["structure_complete"]),
	}, nil
}

func purgeIncompleteImport(ctx context.Context, client *defra.Client, homeDir *home.Dir, bookID string) error {
	pageIDs, err := queryDocIDs(ctx, client, fmt.Sprintf(`{ Page(filter: {_bookID: {_eq: %q}}) { _docID } }`, bookID), "Page")
	if err != nil {
		return err
	}
	chapterIDs, err := queryDocIDs(ctx, client, fmt.Sprintf(`{ Chapter(filter: {_bookID: {_eq: %q}}) { _docID } }`, bookID), "Chapter")
	if err != nil {
		return err
	}
	bookResp, err := client.Query(ctx, fmt.Sprintf(`{ Book(docID: %q) { _tocID } }`, bookID))
	if err != nil {
		return err
	}
	if errMsg := bookResp.Error(); errMsg != "" {
		return fmt.Errorf("query incomplete EPUB Book: %s", errMsg)
	}
	tocID := ""
	if rows, ok := bookResp.Data["Book"].([]any); ok && len(rows) > 0 {
		if row, ok := rows[0].(map[string]any); ok {
			tocID = stringField(row["_tocID"])
		}
	}

	for _, pageID := range pageIDs {
		ids, queryErr := queryDocIDs(ctx, client, fmt.Sprintf(`{ OcrResult(filter: {_pageID: {_eq: %q}}) { _docID } }`, pageID), "OcrResult")
		if queryErr != nil {
			return queryErr
		}
		for _, id := range ids {
			if err := client.Delete(ctx, "OcrResult", id); err != nil {
				return err
			}
		}
	}
	for _, chapterID := range chapterIDs {
		ids, queryErr := queryDocIDs(ctx, client, fmt.Sprintf(`{ Paragraph(filter: {_chapterID: {_eq: %q}}) { _docID } }`, chapterID), "Paragraph")
		if queryErr != nil {
			return queryErr
		}
		for _, id := range ids {
			if err := client.Delete(ctx, "Paragraph", id); err != nil {
				return err
			}
		}
		if err := client.Delete(ctx, "Chapter", chapterID); err != nil {
			return err
		}
	}
	if tocID != "" {
		ids, queryErr := queryDocIDs(ctx, client, fmt.Sprintf(`{ TocEntry(filter: {_tocID: {_eq: %q}}) { _docID } }`, tocID), "TocEntry")
		if queryErr != nil {
			return queryErr
		}
		for _, id := range ids {
			if err := client.Delete(ctx, "TocEntry", id); err != nil {
				return err
			}
		}
	}
	for _, pageID := range pageIDs {
		if err := client.Delete(ctx, "Page", pageID); err != nil {
			return err
		}
	}
	if tocID != "" {
		if err := client.Delete(ctx, "ToC", tocID); err != nil {
			return err
		}
	}
	if err := client.Delete(ctx, "Book", bookID); err != nil {
		return err
	}
	return os.RemoveAll(homeDir.SourceImagesDir(bookID))
}

func queryDocIDs(ctx context.Context, client *defra.Client, query, collection string) ([]string, error) {
	resp, err := client.Query(ctx, query)
	if err != nil {
		return nil, err
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("query %s cleanup rows: %s", collection, errMsg)
	}
	rows, _ := resp.Data[collection].([]any)
	ids := make([]string, 0, len(rows))
	for _, raw := range rows {
		row, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		if id := stringField(row["_docID"]); id != "" {
			ids = append(ids, id)
		}
	}
	return ids, nil
}

func createManyBatched(ctx context.Context, client *defra.Client, collection string, inputs []map[string]any, returnFields ...string) ([]defra.CreateManyResult, error) {
	var all []defra.CreateManyResult
	for start := 0; start < len(inputs); start += createBatchSize {
		end := min(start+createBatchSize, len(inputs))
		results, err := client.CreateMany(ctx, collection, inputs[start:end], returnFields...)
		all = append(all, results...)
		if err != nil {
			return all, err
		}
	}
	return all, nil
}

func fileSHA256(filename string) (string, error) {
	file, err := os.Open(filename)
	if err != nil {
		return "", fmt.Errorf("open EPUB for hashing: %w", err)
	}
	defer file.Close()
	h := sha256.New()
	if _, err := io.Copy(h, file); err != nil {
		return "", fmt.Errorf("hash EPUB: %w", err)
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func copySource(source, destination string) error {
	in, err := os.Open(source)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(out, in)
	closeErr := out.Close()
	if copyErr != nil {
		return copyErr
	}
	return closeErr
}

func nilIfEmpty(value string) any {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return value
}

func levelName(level int) string {
	if level <= 1 {
		return "chapter"
	}
	return "section"
}

func wordCount(text string) int { return len(strings.Fields(text)) }

func stringField(value any) string {
	result, _ := value.(string)
	return result
}

func boolField(value any) bool {
	result, _ := value.(bool)
	return result
}

func numberField(value any) int {
	switch number := value.(type) {
	case float64:
		return int(number)
	case int:
		return number
	case json.Number:
		result, _ := number.Int64()
		return int(result)
	default:
		return 0
	}
}
