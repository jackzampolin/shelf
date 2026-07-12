package researchmcp

// The wire types intentionally mirror only the stable, read-only subset of
// Shelf's public HTTP API needed by research agents.

type book struct {
	ID                string `json:"id"`
	Title             string `json:"title"`
	Author            string `json:"author,omitempty"`
	PageCount         int    `json:"page_count"`
	Status            string `json:"status"`
	StatusReason      string `json:"status_reason,omitempty"`
	SourceFormat      string `json:"source_format,omitempty"`
	SourceFilename    string `json:"source_filename,omitempty"`
	SourceSHA256      string `json:"source_sha256,omitempty"`
	StructureComplete bool   `json:"structure_complete"`
	StructureFailed   bool   `json:"structure_failed"`
}

type booksResponse struct {
	Books []book `json:"books"`
}

type paragraph struct {
	ID           string `json:"id"`
	SortOrder    int    `json:"sort_order"`
	StartPage    int    `json:"start_page"`
	RawText      string `json:"raw_text,omitempty"`
	PolishedText string `json:"polished_text,omitempty"`
	WordCount    int    `json:"word_count"`
}

type chapter struct {
	ID             string      `json:"id"`
	EntryID        string      `json:"entry_id,omitempty"`
	ParentID       string      `json:"parent_id,omitempty"`
	Title          string      `json:"title"`
	Level          int         `json:"level"`
	LevelName      string      `json:"level_name,omitempty"`
	EntryNumber    string      `json:"entry_number,omitempty"`
	StartPage      int         `json:"start_page"`
	EndPage        int         `json:"end_page"`
	MatterType     string      `json:"matter_type"`
	ContentType    string      `json:"content_type,omitempty"`
	SortOrder      int         `json:"sort_order"`
	Source         string      `json:"source,omitempty"`
	WordCount      int         `json:"word_count,omitempty"`
	PageCount      int         `json:"page_count"`
	PolishComplete bool        `json:"polish_complete"`
	PolishFailed   bool        `json:"polish_failed"`
	PolishedText   string      `json:"polished_text,omitempty"`
	Paragraphs     []paragraph `json:"paragraphs,omitempty"`
}

type chaptersResponse struct {
	BookID      string    `json:"book_id"`
	BookTitle   string    `json:"book_title,omitempty"`
	TotalPages  int       `json:"total_pages"`
	Chapters    []chapter `json:"chapters"`
	HasChapters bool      `json:"has_chapters"`
}

type passage struct {
	ChapterID    string
	ParagraphID  string
	ChapterTitle string
	MatterType   string
	ContentType  string
	StartPage    int
	SortOrder    int
	Text         string
	ContentHash  string
}

type snapshot struct {
	Book            book
	Chapters        []chapter
	Passages        []passage
	StructureDigest string
}
