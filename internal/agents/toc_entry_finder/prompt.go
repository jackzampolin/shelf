package toc_entry_finder

import (
	_ "embed"
	"fmt"
	"strconv"
	"strings"

	"github.com/jackzampolin/shelf/internal/prompts"
)

//go:embed system.tmpl
var systemPrompt string

// SystemPrompt returns the system prompt for the ToC entry finder agent.
func SystemPrompt() string {
	return systemPrompt
}

// PromptKey is the hierarchical key for this prompt.
const PromptKey = "agents.toc_entry_finder.system"

// UserPromptKey is the hierarchical key for the user prompt template.
const UserPromptKey = "agents.toc_entry_finder.user"

//go:embed user.tmpl
var userPromptTemplate string

// RegisterPrompts registers the toc_entry_finder prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         PromptKey,
		Text:        systemPrompt,
		Description: "ToC entry finder agent system prompt - locates where ToC entries appear in scanned books",
	})
	r.Register(prompts.EmbeddedPrompt{
		Key:         UserPromptKey,
		Text:        userPromptTemplate,
		Description: "ToC entry finder agent user prompt template - provides entry details and book context",
	})
}

// BookStructure provides context about the book's layout.
type BookStructure struct {
	TotalPages         int    `json:"total_pages"`
	BackMatterStart    int    `json:"back_matter_start"` // Estimated start of back matter
	BackMatterTypes    string `json:"back_matter_types"` // e.g., "footnotes, bibliography, index"
	TargetIsBackMatter bool   `json:"target_is_back_matter"`
	RetryHint          string `json:"retry_hint,omitempty"`
}

// BuildUserPrompt builds the user prompt for finding a specific ToC entry.
func BuildUserPrompt(entry *TocEntry, totalPages int, bookStructure *BookStructure) string {
	// Build search term: "chapter 5 The Beginning"
	searchParts := []string{}
	if entry.LevelName != "" {
		searchParts = append(searchParts, entry.LevelName)
	} else if entry.Level > 0 {
		searchParts = append(searchParts, fmt.Sprintf("level %d", entry.Level))
	}
	if entry.EntryNumber != "" {
		searchParts = append(searchParts, entry.EntryNumber)
	}
	if entry.Title != "" {
		searchParts = append(searchParts, entry.Title)
	}
	searchTerm := strings.Join(searchParts, " ")

	var prompt strings.Builder
	fmt.Fprintf(&prompt, "TARGET ENTRY\nFind only this ToC entry: %q", searchTerm)

	if entry.PrintedPageNumber != "" {
		fmt.Fprintf(&prompt, "\nPrinted page: %s (use scan pages for the final answer)", entry.PrintedPageNumber)
		if printedPage, err := strconv.Atoi(entry.PrintedPageNumber); err == nil && printedPage > 0 && totalPages > 0 {
			start := clampPage(printedPage+10, totalPages)
			end := clampPage(printedPage+35, totalPages)
			if end < start {
				end = start
			}
			fmt.Fprintf(&prompt, "\nStart near scan pages %d-%d, then expand only if needed.", start, end)
			fmt.Fprintf(&prompt, "\nUse get_heading_pages in that range first. Prioritize target_title_match, target_title_prefix_match, or entry_number_match candidates, verify the best candidate with get_page_ocr, then write_result. Do not inspect the range one page at a time unless candidate tools fail.")
		}
	}

	if totalPages > 0 {
		fmt.Fprintf(&prompt, "\nTotal scan pages: %d", totalPages)
	}

	if bookStructure != nil && strings.TrimSpace(bookStructure.RetryHint) != "" {
		fmt.Fprintf(&prompt, "\n\nPREVIOUS REJECTION FEEDBACK\n%s", strings.TrimSpace(bookStructure.RetryHint))
		fmt.Fprintf(&prompt, "\nDo not repeat a rejected scan_page unless get_page_ocr now shows opener-quality evidence: a matching section/chapter header, title_prefix_in_section_header for an appendix/diagram title, matching entry-number section header, the first page of a title page-header cluster, or expected_printed_page_missing at that cluster boundary. Use the tools to inspect another candidate before calling write_result again.")
	}

	fmt.Fprintf(&prompt, "\n\nDECISION RULE\nIf grep_text shows a dense title cluster near the expected scan range, verify the first cluster page with get_page_ocr. Prefer a formal section/chapter header. For appendix/diagram entries, evidence.title_prefix_in_section_header is valid when the remaining title continues on an adjacent page. If get_page_ocr returns write_result_ready=true, call write_result with write_result_args; do not continue scanning. A page-header title is valid only on the first page of the cluster; later repeated running headers are not entry starts. If get_page_ocr reports expected_printed_page_missing at the start of a title-header cluster, use that first available scanned page.")

	// Add book structure context
	if bookStructure != nil && bookStructure.BackMatterStart > 0 {
		labels := strings.TrimSpace(bookStructure.BackMatterTypes)
		if labels == "" {
			labels = "late notes, appendices, glossary, index"
		}
		fmt.Fprintf(&prompt, "\n\nPAGE CONTEXT\nLate-section labels in this book: %s.\n", labels)
		if bookStructure.TargetIsBackMatter {
			fmt.Fprintf(&prompt, "This target is a late/back-matter ToC entry, so pages around or after scan page %d may be valid.\n", bookStructure.BackMatterStart)
			fmt.Fprintf(&prompt, "Do not return a generic late-section label; the only target is %q.", searchTerm)
		} else {
			fmt.Fprintf(&prompt, "Pages %d+ are likely late notes, appendices, glossary, or index material.\n", bookStructure.BackMatterStart)
			fmt.Fprintf(&prompt, "For this non-back-matter target, treat matches there as references unless OCR clearly shows this exact entry starts there.\n")
			fmt.Fprintf(&prompt, "Do not search for or return the late-section labels; the only target is %q.", searchTerm)
		}
	}

	return prompt.String()
}

func clampPage(page, totalPages int) int {
	if page < 1 {
		return 1
	}
	if totalPages > 0 && page > totalPages {
		return totalPages
	}
	return page
}
