package epubimport

import (
	"path/filepath"
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/epub"
)

func TestParseShelfEPUBPreservesMetadataAndChapters(t *testing.T) {
	filename := filepath.Join(t.TempDir(), "book.epub")
	builder := epub.NewBuilder(epub.Book{
		ID: "source-id", Title: "Direct Import", Author: "Ada Reader", Language: "en",
	}, []epub.Chapter{
		{ID: "front", Title: "Preface", Level: 1, MatterType: "front_matter", SortOrder: 1, PolishedText: "This is the preface paragraph with enough source text."},
		{ID: "one", Title: "Chapter One", Level: 1, MatterType: "body", SortOrder: 2, PolishedText: "# A Heading\n\nThis is the first chapter paragraph.\n\nThis is another paragraph."},
		{ID: "index", Title: "Index", Level: 1, MatterType: "back_matter", SortOrder: 3, PolishedText: "Alpha, 1\n\nBeta, 2\n\nGamma, 3"},
	})
	if err := builder.Build(filename); err != nil {
		t.Fatalf("build fixture EPUB: %v", err)
	}

	publication, err := Parse(filename)
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if publication.Title != "Direct Import" {
		t.Fatalf("Title = %q", publication.Title)
	}
	if len(publication.Authors) != 1 || publication.Authors[0] != "Ada Reader" {
		t.Fatalf("Authors = %#v", publication.Authors)
	}
	if got, want := len(publication.Chapters), 3; got != want {
		t.Fatalf("chapters = %d, want %d: %#v", got, want, publication.Chapters)
	}
	if publication.Chapters[0].ContentType != "preface" || !publication.Chapters[0].AudioInclude {
		t.Fatalf("preface classification = %#v", publication.Chapters[0])
	}
	if !strings.Contains(publication.Chapters[1].Markdown, "first chapter paragraph") {
		t.Fatalf("chapter markdown lost source text: %q", publication.Chapters[1].Markdown)
	}
	if publication.Chapters[2].ContentType != "index" || publication.Chapters[2].AudioInclude {
		t.Fatalf("index classification = %#v", publication.Chapters[2])
	}
}

func TestParseSplitsSingleDocumentAtNavigationAnchors(t *testing.T) {
	filename := writeRawEPUB(t, map[string]string{
		"META-INF/container.xml": `<?xml version="1.0"?><container><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>`,
		"OPS/package.opf":        `<?xml version="1.0"?><package><metadata><title>Anchors</title><creator>Writer</creator><language>en</language></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="book" href="book.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="book"/></spine></package>`,
		"OPS/nav.xhtml":          `<html><body><nav epub:type="toc"><ol><li><a href="book.xhtml#one">One</a></li><li><a href="book.xhtml#two">Two</a><ol><li><a href="book.xhtml#subtitle">A Subtitle</a></li></ol></li></ol></nav></body></html>`,
		"OPS/book.xhtml":         `<html><body><h1 id="one">One</h1><p>First chapter source paragraph is long enough.</p><h1 id="two">Two</h1><h2 id="subtitle">A Subtitle</h2><p>Second chapter source paragraph is long enough.</p></body></html>`,
	})
	publication, err := Parse(filename)
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if got, want := len(publication.Chapters), 2; got != want {
		t.Fatalf("chapters = %d, want %d: %#v", got, want, publication.Chapters)
	}
	if publication.Chapters[0].Title != "One" || strings.Contains(publication.Chapters[0].Markdown, "Second chapter") {
		t.Fatalf("first split = %#v", publication.Chapters[0])
	}
	if publication.Chapters[1].Title != "Two" || !strings.Contains(publication.Chapters[1].Markdown, "Second chapter") {
		t.Fatalf("second split = %#v", publication.Chapters[1])
	}
	if !strings.Contains(publication.Chapters[1].Markdown, "A Subtitle") {
		t.Fatalf("sole adjacent navigation subtitle was not merged: %#v", publication.Chapters[1])
	}
}
