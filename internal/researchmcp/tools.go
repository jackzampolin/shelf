package researchmcp

import (
	"context"
	"fmt"
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type GetBookInput struct {
	BookID string `json:"book_id" jsonschema:"Shelf book document ID"`
}

type GetBookOutput struct {
	BookID            string `json:"book_id"`
	Title             string `json:"title"`
	Author            string `json:"author,omitempty"`
	Status            string `json:"status"`
	StatusReason      string `json:"status_reason,omitempty"`
	PageCount         int    `json:"page_count"`
	SourceFormat      string `json:"source_format,omitempty"`
	SourceFilename    string `json:"source_filename,omitempty"`
	SourceSHA256      string `json:"source_sha256"`
	StructureComplete bool   `json:"structure_complete"`
	StructureFailed   bool   `json:"structure_failed"`
	StructureDigest   string `json:"structure_digest"`
	ChapterCount      int    `json:"chapter_count"`
	PassageCount      int    `json:"passage_count"`
	ResearchReady     bool   `json:"research_ready"`
}

type ListStructureInput struct {
	BookID     string `json:"book_id" jsonschema:"Shelf book document ID"`
	MatterType string `json:"matter_type,omitempty" jsonschema:"Optional exact matter type filter such as body or front_matter"`
	Offset     int    `json:"offset,omitempty" jsonschema:"Zero-based chapter offset"`
	Limit      int    `json:"limit,omitempty" jsonschema:"Maximum chapters to return, default 50 and maximum 200"`
}

type ChapterView struct {
	ChapterID      string `json:"chapter_id"`
	ParentID       string `json:"parent_id,omitempty"`
	EntryID        string `json:"entry_id,omitempty"`
	Title          string `json:"title"`
	Level          int    `json:"level"`
	LevelName      string `json:"level_name,omitempty"`
	EntryNumber    string `json:"entry_number,omitempty"`
	StartPage      int    `json:"start_page"`
	EndPage        int    `json:"end_page"`
	MatterType     string `json:"matter_type"`
	ContentType    string `json:"content_type,omitempty"`
	SortOrder      int    `json:"sort_order"`
	WordCount      int    `json:"word_count,omitempty"`
	Paragraphs     int    `json:"paragraph_count"`
	PolishComplete bool   `json:"polish_complete"`
	PolishFailed   bool   `json:"polish_failed"`
}

type ListStructureOutput struct {
	BookID          string        `json:"book_id"`
	SourceSHA256    string        `json:"source_sha256"`
	StructureDigest string        `json:"structure_digest"`
	Total           int           `json:"total"`
	Offset          int           `json:"offset"`
	NextOffset      *int          `json:"next_offset,omitempty"`
	Chapters        []ChapterView `json:"chapters"`
}

type SearchPassagesInput struct {
	BookID        string   `json:"book_id" jsonschema:"Shelf book document ID"`
	Query         string   `json:"query" jsonschema:"Literal text or RE2 regular expression to search for"`
	Regex         bool     `json:"regex,omitempty" jsonschema:"Interpret query as an RE2 regular expression"`
	CaseSensitive bool     `json:"case_sensitive,omitempty"`
	ChapterIDs    []string `json:"chapter_ids,omitempty" jsonschema:"Optional chapter ID scope"`
	MatterType    string   `json:"matter_type,omitempty"`
	TopK          int      `json:"top_k,omitempty" jsonschema:"Maximum matches, default 10 and maximum 50"`
	SnippetChars  int      `json:"snippet_chars,omitempty" jsonschema:"Maximum snippet runes, default 500 and maximum 1200"`
}

type PassageMatch struct {
	ChapterID    string `json:"chapter_id"`
	ParagraphID  string `json:"paragraph_id,omitempty"`
	ChapterTitle string `json:"chapter_title"`
	MatterType   string `json:"matter_type,omitempty"`
	Page         int    `json:"page,omitempty"`
	StartChar    int    `json:"start_char"`
	EndChar      int    `json:"end_char"`
	SnippetStart int    `json:"snippet_start"`
	SnippetEnd   int    `json:"snippet_end"`
	Snippet      string `json:"snippet"`
	ContentHash  string `json:"content_hash"`
}

type SearchPassagesOutput struct {
	BookID          string         `json:"book_id"`
	SourceSHA256    string         `json:"source_sha256"`
	StructureDigest string         `json:"structure_digest"`
	Query           string         `json:"query"`
	Matches         []PassageMatch `json:"matches"`
	Truncated       bool           `json:"truncated"`
}

type ReadPassageInput struct {
	BookID        string `json:"book_id"`
	ChapterID     string `json:"chapter_id"`
	ParagraphID   string `json:"paragraph_id,omitempty"`
	StartChar     int    `json:"start_char,omitempty" jsonschema:"Rune offset within the selected canonical passage"`
	ContextBefore int    `json:"context_before,omitempty" jsonschema:"Runes to include before start_char, default 300 and maximum 2000"`
	MaxChars      int    `json:"max_chars,omitempty" jsonschema:"Maximum returned runes, default 4000 and maximum 12000"`
}

type ReadPassageOutput struct {
	BookID          string `json:"book_id"`
	SourceSHA256    string `json:"source_sha256"`
	StructureDigest string `json:"structure_digest"`
	ChapterID       string `json:"chapter_id"`
	ParagraphID     string `json:"paragraph_id,omitempty"`
	ChapterTitle    string `json:"chapter_title"`
	Page            int    `json:"page,omitempty"`
	StartChar       int    `json:"start_char"`
	EndChar         int    `json:"end_char"`
	TotalChars      int    `json:"total_chars"`
	Text            string `json:"text"`
	ContentHash     string `json:"content_hash"`
	HasBefore       bool   `json:"has_before"`
	HasAfter        bool   `json:"has_after"`
}

type ValidateQuoteInput struct {
	BookID                  string `json:"book_id"`
	Quote                   string `json:"quote" jsonschema:"Exact verbatim quotation to validate"`
	ChapterID               string `json:"chapter_id,omitempty"`
	ParagraphID             string `json:"paragraph_id,omitempty"`
	ExpectedSourceSHA256    string `json:"expected_source_sha256,omitempty"`
	ExpectedStructureDigest string `json:"expected_structure_digest,omitempty"`
}

type QuoteOccurrence struct {
	ChapterID    string `json:"chapter_id"`
	ParagraphID  string `json:"paragraph_id,omitempty"`
	ChapterTitle string `json:"chapter_title"`
	Page         int    `json:"page,omitempty"`
	StartChar    int    `json:"start_char"`
	EndChar      int    `json:"end_char"`
	ContentHash  string `json:"content_hash"`
	Context      string `json:"context"`
}

type ValidateQuoteOutput struct {
	BookID          string            `json:"book_id"`
	SourceSHA256    string            `json:"source_sha256"`
	StructureDigest string            `json:"structure_digest"`
	ExactMatch      bool              `json:"exact_match"`
	VersionMatch    bool              `json:"version_match"`
	Occurrences     []QuoteOccurrence `json:"occurrences"`
	Truncated       bool              `json:"truncated"`
	Message         string            `json:"message"`
}

func NewServer(client *Client, version string) *mcp.Server {
	server := mcp.NewServer(&mcp.Implementation{Name: "shelf-research", Version: version}, nil)
	mcp.AddTool(server, &mcp.Tool{Name: "shelf_get_book", Description: "Get research-ready Shelf book metadata and the current canonical structure digest."}, client.getBook)
	mcp.AddTool(server, &mcp.Tool{Name: "shelf_list_structure", Description: "List bounded chapter metadata without returning book text."}, client.listStructure)
	mcp.AddTool(server, &mcp.Tool{Name: "shelf_search_passages", Description: "Search canonical parsed passages using literal text or an RE2 expression and return bounded snippets with stable locators."}, client.searchPassages)
	mcp.AddTool(server, &mcp.Tool{Name: "shelf_read_passage", Description: "Read a bounded window from one canonical chapter or paragraph."}, client.readPassage)
	mcp.AddTool(server, &mcp.Tool{Name: "shelf_validate_quote", Description: "Deterministically verify an exact quotation against a pinned canonical Shelf version."}, client.validateQuote)
	return server
}

func (c *Client) getBook(ctx context.Context, _ *mcp.CallToolRequest, in GetBookInput) (*mcp.CallToolResult, GetBookOutput, error) {
	s, err := c.loadSnapshot(ctx, in.BookID)
	if err != nil {
		return nil, GetBookOutput{}, err
	}
	return nil, GetBookOutput{
		BookID: s.Book.ID, Title: s.Book.Title, Author: s.Book.Author, Status: s.Book.Status,
		StatusReason: s.Book.StatusReason, PageCount: s.Book.PageCount, SourceFormat: s.Book.SourceFormat,
		SourceFilename: s.Book.SourceFilename, SourceSHA256: s.Book.SourceSHA256,
		StructureComplete: s.Book.StructureComplete, StructureFailed: s.Book.StructureFailed,
		StructureDigest: s.StructureDigest, ChapterCount: len(s.Chapters), PassageCount: len(s.Passages),
		ResearchReady: requireResearchReady(s) == nil,
	}, nil
}

func (c *Client) listStructure(ctx context.Context, _ *mcp.CallToolRequest, in ListStructureInput) (*mcp.CallToolResult, ListStructureOutput, error) {
	s, err := c.loadSnapshot(ctx, in.BookID)
	if err != nil {
		return nil, ListStructureOutput{}, err
	}
	if err := requireResearchReady(s); err != nil {
		return nil, ListStructureOutput{}, err
	}
	var filtered []chapter
	for _, ch := range s.Chapters {
		if in.MatterType == "" || ch.MatterType == in.MatterType {
			filtered = append(filtered, ch)
		}
	}
	offset := clamp(in.Offset, 0, len(filtered))
	limit := in.Limit
	if limit <= 0 {
		limit = 50
	}
	if limit > 200 {
		limit = 200
	}
	end := offset + limit
	if end > len(filtered) {
		end = len(filtered)
	}
	out := ListStructureOutput{BookID: s.Book.ID, SourceSHA256: s.Book.SourceSHA256, StructureDigest: s.StructureDigest, Total: len(filtered), Offset: offset, Chapters: make([]ChapterView, 0, end-offset)}
	for _, ch := range filtered[offset:end] {
		out.Chapters = append(out.Chapters, ChapterView{ChapterID: ch.ID, ParentID: ch.ParentID, EntryID: ch.EntryID, Title: ch.Title, Level: ch.Level, LevelName: ch.LevelName, EntryNumber: ch.EntryNumber, StartPage: ch.StartPage, EndPage: ch.EndPage, MatterType: ch.MatterType, ContentType: ch.ContentType, SortOrder: ch.SortOrder, WordCount: ch.WordCount, Paragraphs: len(ch.Paragraphs), PolishComplete: ch.PolishComplete, PolishFailed: ch.PolishFailed})
	}
	if end < len(filtered) {
		next := end
		out.NextOffset = &next
	}
	return nil, out, nil
}

func (c *Client) searchPassages(ctx context.Context, _ *mcp.CallToolRequest, in SearchPassagesInput) (*mcp.CallToolResult, SearchPassagesOutput, error) {
	s, err := c.loadSnapshot(ctx, in.BookID)
	if err != nil {
		return nil, SearchPassagesOutput{}, err
	}
	if err := requireResearchReady(s); err != nil {
		return nil, SearchPassagesOutput{}, err
	}
	if strings.TrimSpace(in.Query) == "" {
		return nil, SearchPassagesOutput{}, fmt.Errorf("query is required")
	}
	topK := in.TopK
	if topK <= 0 {
		topK = 10
	}
	if topK > 50 {
		topK = 50
	}
	snippetChars := in.SnippetChars
	if snippetChars <= 0 {
		snippetChars = 500
	}
	if snippetChars > 1200 {
		snippetChars = 1200
	}
	chapterScope := make(map[string]bool, len(in.ChapterIDs))
	for _, id := range in.ChapterIDs {
		chapterScope[id] = true
	}
	matcher, err := compileMatcher(in.Query, in.Regex, in.CaseSensitive)
	if err != nil {
		return nil, SearchPassagesOutput{}, err
	}
	out := SearchPassagesOutput{BookID: s.Book.ID, SourceSHA256: s.Book.SourceSHA256, StructureDigest: s.StructureDigest, Query: in.Query, Matches: make([]PassageMatch, 0, topK)}
	for _, p := range s.Passages {
		if len(chapterScope) > 0 && !chapterScope[p.ChapterID] {
			continue
		}
		if in.MatterType != "" && p.MatterType != in.MatterType {
			continue
		}
		for _, loc := range matcher(p.Text) {
			if len(out.Matches) >= topK {
				out.Truncated = true
				return nil, out, nil
			}
			runes := []rune(p.Text)
			half := snippetChars / 2
			ss := loc[0] - half
			if ss < 0 {
				ss = 0
			}
			se := ss + snippetChars
			if se > len(runes) {
				se = len(runes)
				ss = se - snippetChars
				if ss < 0 {
					ss = 0
				}
			}
			out.Matches = append(out.Matches, PassageMatch{ChapterID: p.ChapterID, ParagraphID: p.ParagraphID, ChapterTitle: p.ChapterTitle, MatterType: p.MatterType, Page: p.StartPage, StartChar: loc[0], EndChar: loc[1], SnippetStart: ss, SnippetEnd: se, Snippet: string(runes[ss:se]), ContentHash: p.ContentHash})
		}
	}
	return nil, out, nil
}

func (c *Client) readPassage(ctx context.Context, _ *mcp.CallToolRequest, in ReadPassageInput) (*mcp.CallToolResult, ReadPassageOutput, error) {
	s, err := c.loadSnapshot(ctx, in.BookID)
	if err != nil {
		return nil, ReadPassageOutput{}, err
	}
	if err := requireResearchReady(s); err != nil {
		return nil, ReadPassageOutput{}, err
	}
	p, err := findPassage(s, in.ChapterID, in.ParagraphID)
	if err != nil {
		return nil, ReadPassageOutput{}, err
	}
	maxChars := in.MaxChars
	if maxChars <= 0 {
		maxChars = 4000
	}
	if maxChars > 12000 {
		maxChars = 12000
	}
	before := in.ContextBefore
	if before <= 0 {
		before = 300
	}
	if before > 2000 {
		before = 2000
	}
	runes := []rune(p.Text)
	anchor := clamp(in.StartChar, 0, len(runes))
	start := anchor - before
	if start < 0 {
		start = 0
	}
	end := start + maxChars
	if end > len(runes) {
		end = len(runes)
	}
	return nil, ReadPassageOutput{BookID: s.Book.ID, SourceSHA256: s.Book.SourceSHA256, StructureDigest: s.StructureDigest, ChapterID: p.ChapterID, ParagraphID: p.ParagraphID, ChapterTitle: p.ChapterTitle, Page: p.StartPage, StartChar: start, EndChar: end, TotalChars: len(runes), Text: string(runes[start:end]), ContentHash: p.ContentHash, HasBefore: start > 0, HasAfter: end < len(runes)}, nil
}

func (c *Client) validateQuote(ctx context.Context, _ *mcp.CallToolRequest, in ValidateQuoteInput) (*mcp.CallToolResult, ValidateQuoteOutput, error) {
	s, err := c.loadSnapshot(ctx, in.BookID)
	if err != nil {
		return nil, ValidateQuoteOutput{}, err
	}
	if err := requireResearchReady(s); err != nil {
		return nil, ValidateQuoteOutput{}, err
	}
	quote := strings.TrimSpace(in.Quote)
	if quote == "" {
		return nil, ValidateQuoteOutput{}, fmt.Errorf("quote is required")
	}
	versionMatch := (in.ExpectedSourceSHA256 == "" || in.ExpectedSourceSHA256 == s.Book.SourceSHA256) && (in.ExpectedStructureDigest == "" || in.ExpectedStructureDigest == s.StructureDigest)
	out := ValidateQuoteOutput{BookID: s.Book.ID, SourceSHA256: s.Book.SourceSHA256, StructureDigest: s.StructureDigest, VersionMatch: versionMatch, Occurrences: make([]QuoteOccurrence, 0, 1)}
	if !versionMatch {
		out.Message = "source version mismatch; refresh the assignment before citing"
		return nil, out, nil
	}
	for _, p := range s.Passages {
		if in.ChapterID != "" && p.ChapterID != in.ChapterID {
			continue
		}
		if in.ParagraphID != "" && p.ParagraphID != in.ParagraphID {
			continue
		}
		startByte := 0
		for {
			i := strings.Index(p.Text[startByte:], quote)
			if i < 0 {
				break
			}
			i += startByte
			start := utf8.RuneCountInString(p.Text[:i])
			end := start + utf8.RuneCountInString(quote)
			runes := []rune(p.Text)
			cs := start - 180
			if cs < 0 {
				cs = 0
			}
			ce := end + 180
			if ce > len(runes) {
				ce = len(runes)
			}
			if len(out.Occurrences) >= 20 {
				out.Truncated = true
				break
			}
			out.Occurrences = append(out.Occurrences, QuoteOccurrence{ChapterID: p.ChapterID, ParagraphID: p.ParagraphID, ChapterTitle: p.ChapterTitle, Page: p.StartPage, StartChar: start, EndChar: end, ContentHash: p.ContentHash, Context: string(runes[cs:ce])})
			startByte = i + len(quote)
			if startByte >= len(p.Text) {
				break
			}
		}
		if out.Truncated {
			break
		}
	}
	out.ExactMatch = len(out.Occurrences) > 0
	if out.ExactMatch {
		out.Message = "exact quotation found in the pinned canonical Shelf text"
	} else {
		out.Message = "quotation was not found exactly; copy it again from shelf_read_passage"
	}
	return nil, out, nil
}

func findPassage(s *snapshot, chapterID, paragraphID string) (passage, error) {
	if chapterID == "" {
		return passage{}, fmt.Errorf("chapter_id is required")
	}
	for _, p := range s.Passages {
		if p.ChapterID == chapterID && (paragraphID == "" || p.ParagraphID == paragraphID) {
			return p, nil
		}
	}
	return passage{}, fmt.Errorf("canonical passage not found for chapter_id=%q paragraph_id=%q", chapterID, paragraphID)
}

func compileMatcher(query string, isRegex, caseSensitive bool) (func(string) [][2]int, error) {
	pattern := regexp.QuoteMeta(query)
	if isRegex {
		pattern = query
	}
	if !caseSensitive {
		pattern = "(?i)" + pattern
	}
	re, err := regexp.Compile(pattern)
	if err != nil {
		return nil, fmt.Errorf("invalid search regex: %w", err)
	}
	return func(text string) [][2]int {
		raw := re.FindAllStringIndex(text, -1)
		out := make([][2]int, 0, len(raw))
		for _, m := range raw {
			out = append(out, [2]int{utf8.RuneCountInString(text[:m[0]]), utf8.RuneCountInString(text[:m[1]])})
		}
		return out
	}, nil
}

func clamp(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
