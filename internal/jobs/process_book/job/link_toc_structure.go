package job

import (
	"context"
	"strings"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

func (j *Job) tocEntryBookStructure(ctx context.Context, entry *toc_entry_finder.TocEntry) *toc_entry_finder.BookStructure {
	if j.Book.GetFinalizePatternResult() == nil {
		j.loadExistingPatternResults(ctx)
	}

	entries := j.tocEntriesForStructure(ctx)

	return &toc_entry_finder.BookStructure{
		TotalPages:         j.Book.TotalPages,
		BackMatterStart:    deriveBackMatterStart(j.Book.TotalPages, j.Book.GetFinalizePatternResult()),
		BackMatterTypes:    deriveBackMatterTypes(j.Book.GetFinalizePatternResult(), entries),
		TargetIsBackMatter: tocEntryIsBackMatter(entry, entries),
	}
}

func (j *Job) tocEntriesForStructure(ctx context.Context) []*toc_entry_finder.TocEntry {
	byDocID := make(map[string]*toc_entry_finder.TocEntry)
	add := func(entry *toc_entry_finder.TocEntry) {
		if entry == nil || entry.DocID == "" {
			return
		}
		if _, exists := byDocID[entry.DocID]; exists {
			return
		}
		byDocID[entry.DocID] = entry
	}

	for _, entry := range j.Book.GetTocEntries() {
		add(entry)
	}
	for _, entry := range j.LinkTocEntries {
		add(entry)
	}
	for _, entry := range j.loadTocEntriesForStructure(ctx) {
		add(entry)
	}

	entries := make([]*toc_entry_finder.TocEntry, 0, len(byDocID))
	for _, entry := range byDocID {
		entries = append(entries, entry)
	}
	return entries
}

func (j *Job) loadTocEntriesForStructure(ctx context.Context) []*toc_entry_finder.TocEntry {
	if j.Book == nil || j.TocDocID == "" {
		return nil
	}

	linkedEntries := j.Book.GetLinkedEntries()
	if len(linkedEntries) == 0 {
		loaded, err := common.RefreshLinkedEntries(ctx, j.Book, j.TocDocID)
		if err != nil {
			if logger := svcctx.LoggerFrom(ctx); logger != nil {
				logger.Debug("could not load full ToC sequence for structure context",
					"book_id", j.Book.BookID,
					"toc_doc_id", j.TocDocID,
					"error", err)
			}
			return nil
		}
		linkedEntries = loaded
	}

	entries := make([]*toc_entry_finder.TocEntry, 0, len(linkedEntries))
	for _, linked := range linkedEntries {
		if linked == nil || linked.DocID == "" {
			continue
		}
		entries = append(entries, &toc_entry_finder.TocEntry{
			DocID:             linked.DocID,
			EntryNumber:       linked.EntryNumber,
			Title:             linked.Title,
			Level:             linked.Level,
			LevelName:         linked.LevelName,
			PrintedPageNumber: linked.PrintedPageNumber,
			SortOrder:         linked.SortOrder,
		})
	}
	return entries
}

func deriveBackMatterStart(totalPages int, pattern *common.FinalizePatternResult) int {
	if pattern != nil {
		start := 0
		for _, excluded := range pattern.Excluded {
			if excluded.StartPage < 1 {
				continue
			}
			if totalPages > 0 && excluded.StartPage > totalPages {
				continue
			}
			if !excludedRangeLooksBackMatter(excluded, totalPages) {
				continue
			}
			if start == 0 || excluded.StartPage < start {
				start = excluded.StartPage
			}
		}
		if start > 0 {
			return start
		}
	}

	if totalPages <= 0 {
		return 0
	}
	start := int(float64(totalPages) * 0.9)
	if start < 1 {
		return 1
	}
	return start
}

func excludedRangeLooksBackMatter(excluded common.ExcludedRange, totalPages int) bool {
	if _, ok := backMatterLabelFromText(excluded.Reason); ok {
		return true
	}
	if totalPages <= 0 {
		return false
	}
	return excluded.StartPage >= int(float64(totalPages)*0.85)
}

func deriveBackMatterTypes(pattern *common.FinalizePatternResult, entries []*toc_entry_finder.TocEntry) string {
	var labels []string
	seen := make(map[string]bool)
	add := func(label string) {
		if label == "" || seen[label] {
			return
		}
		seen[label] = true
		labels = append(labels, label)
	}

	for _, entry := range entries {
		if label, ok := backMatterLabelFromText(entry.Title); ok {
			add(label)
		}
	}
	if pattern != nil {
		for _, excluded := range pattern.Excluded {
			if label, ok := backMatterLabelFromText(excluded.Reason); ok {
				add(label)
			}
		}
	}
	if len(labels) == 0 {
		labels = []string{"late notes", "appendices", "glossary", "index"}
	}
	return strings.Join(labels, ", ")
}

func tocEntryIsBackMatter(entry *toc_entry_finder.TocEntry, entries []*toc_entry_finder.TocEntry) bool {
	if entry == nil {
		return false
	}
	if _, ok := backMatterLabelFromText(entry.Title); ok {
		return true
	}

	firstBackMatterSort := 0
	for _, candidate := range entries {
		if candidate == nil {
			continue
		}
		if _, ok := backMatterLabelFromText(candidate.Title); !ok {
			continue
		}
		if candidate.SortOrder > 0 && (firstBackMatterSort == 0 || candidate.SortOrder < firstBackMatterSort) {
			firstBackMatterSort = candidate.SortOrder
		}
	}
	return firstBackMatterSort > 0 && entry.SortOrder >= firstBackMatterSort
}

func backMatterLabelFromText(text string) (string, bool) {
	lower := strings.ToLower(text)
	switch {
	case strings.Contains(lower, "acknowledg"):
		return "acknowledgments", true
	case strings.Contains(lower, "footnote"):
		return "footnotes", true
	case strings.Contains(lower, "endnote"):
		return "endnotes", true
	case strings.Contains(lower, "appendix") || strings.Contains(lower, "appendices"):
		return "appendices", true
	case strings.Contains(lower, "glossary"):
		return "glossary", true
	case strings.Contains(lower, "bibliograph"):
		return "bibliography", true
	case strings.Contains(lower, "references"):
		return "references", true
	case strings.Contains(lower, "index"):
		return "index", true
	case strings.Contains(lower, "back matter"):
		return "back matter", true
	default:
		return "", false
	}
}
