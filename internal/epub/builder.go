// Package epub provides ePub 3.0 generation from processed book data.
package epub

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/google/uuid"
)

// Book contains the metadata needed for epub generation.
type Book struct {
	ID        string
	Title     string
	Author    string
	Language  string // ISO 639-1 code (e.g., "en")
	Publisher string
	ISBN      string
	CreatedAt time.Time
}

// Chapter represents a chapter for epub generation.
type Chapter struct {
	ID           string // Unique identifier (e.g., "ch_001")
	Title        string
	Level        int    // Hierarchy level (1=part, 2=chapter, 3=section)
	LevelName    string // e.g., "chapter", "part", "epilogue"
	EntryNumber  string // e.g., "1", "I", "A"
	MatterType   string // "front_matter", "body", "back_matter"
	PolishedText string // Markdown-formatted text
	SortOrder    int
}

// Builder creates ePub 3.0 files.
type Builder struct {
	book     Book
	chapters []Chapter
}

// NewBuilder creates a new epub builder.
func NewBuilder(book Book, chapters []Chapter) *Builder {
	return &Builder{
		book:     book,
		chapters: chapters,
	}
}

// Build generates the epub and writes it to the specified path.
func (b *Builder) Build(outputPath string) error {
	// Create output directory if needed
	if err := os.MkdirAll(filepath.Dir(outputPath), 0755); err != nil {
		return fmt.Errorf("failed to create output directory: %w", err)
	}

	// Create output file
	f, err := os.Create(outputPath)
	if err != nil {
		return fmt.Errorf("failed to create output file: %w", err)
	}
	defer f.Close()

	return b.WriteTo(f)
}

// WriteTo writes the epub to a writer.
func (b *Builder) WriteTo(w io.Writer) error {
	zw := zip.NewWriter(w)
	defer zw.Close()

	// 1. Write mimetype (must be first, uncompressed)
	if err := b.writeMimetype(zw); err != nil {
		return err
	}

	// 2. Write META-INF/container.xml
	if err := b.writeContainer(zw); err != nil {
		return err
	}

	// 3. Write OEBPS/content.opf (package document)
	if err := b.writePackage(zw); err != nil {
		return err
	}

	// 4. Write OEBPS/nav.xhtml (navigation)
	if err := b.writeNavigation(zw); err != nil {
		return err
	}

	// 5. Write OEBPS/toc.ncx (NCX for ePub 2 compatibility)
	if err := b.writeNCX(zw); err != nil {
		return err
	}

	// 6. Write OEBPS/styles/style.css
	if err := b.writeStylesheet(zw); err != nil {
		return err
	}

	// 7. Write chapter files
	for i, ch := range b.chapters {
		if err := b.writeChapter(zw, i, ch); err != nil {
			return fmt.Errorf("failed to write chapter %s: %w", ch.ID, err)
		}
	}

	return nil
}

// writeMimetype writes the mimetype file (must be first and uncompressed).
func (b *Builder) writeMimetype(zw *zip.Writer) error {
	// Create with Store method (no compression) as required by ePub spec
	header := &zip.FileHeader{
		Name:   "mimetype",
		Method: zip.Store,
	}
	w, err := zw.CreateHeader(header)
	if err != nil {
		return fmt.Errorf("failed to create mimetype: %w", err)
	}
	_, err = w.Write([]byte("application/epub+zip"))
	return err
}

// writeContainer writes META-INF/container.xml.
func (b *Builder) writeContainer(zw *zip.Writer) error {
	content := `<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>`

	w, err := zw.Create("META-INF/container.xml")
	if err != nil {
		return fmt.Errorf("failed to create container.xml: %w", err)
	}
	_, err = w.Write([]byte(content))
	return err
}

// writePackage writes OEBPS/content.opf.
func (b *Builder) writePackage(zw *zip.Writer) error {
	w, err := zw.Create("OEBPS/content.opf")
	if err != nil {
		return fmt.Errorf("failed to create content.opf: %w", err)
	}

	content := b.generatePackage()
	_, err = w.Write([]byte(content))
	return err
}

// writeNavigation writes OEBPS/nav.xhtml.
func (b *Builder) writeNavigation(zw *zip.Writer) error {
	w, err := zw.Create("OEBPS/nav.xhtml")
	if err != nil {
		return fmt.Errorf("failed to create nav.xhtml: %w", err)
	}

	content := b.generateNavigation()
	_, err = w.Write([]byte(content))
	return err
}

// writeNCX writes OEBPS/toc.ncx for ePub 2 compatibility.
func (b *Builder) writeNCX(zw *zip.Writer) error {
	w, err := zw.Create("OEBPS/toc.ncx")
	if err != nil {
		return fmt.Errorf("failed to create toc.ncx: %w", err)
	}

	content := b.generateNCX()
	_, err = w.Write([]byte(content))
	return err
}

// writeStylesheet writes OEBPS/styles/style.css.
func (b *Builder) writeStylesheet(zw *zip.Writer) error {
	w, err := zw.Create("OEBPS/styles/style.css")
	if err != nil {
		return fmt.Errorf("failed to create style.css: %w", err)
	}

	_, err = w.Write([]byte(defaultStylesheet))
	return err
}

// writeChapter writes a single chapter XHTML file.
func (b *Builder) writeChapter(zw *zip.Writer, index int, ch Chapter) error {
	filename := fmt.Sprintf("OEBPS/chapters/%s.xhtml", ch.ID)
	w, err := zw.Create(filename)
	if err != nil {
		return fmt.Errorf("failed to create %s: %w", filename, err)
	}

	content := b.generateChapterXHTML(ch)
	_, err = w.Write([]byte(content))
	return err
}

// generateUUID generates a unique identifier for the epub.
func (b *Builder) generateUUID() string {
	if b.book.ISBN != "" {
		return "urn:isbn:" + b.book.ISBN
	}
	return "urn:uuid:" + uuid.New().String()
}

// BuildToBuffer generates the epub and returns it as a byte buffer.
func (b *Builder) BuildToBuffer() (*bytes.Buffer, error) {
	buf := new(bytes.Buffer)
	if err := b.WriteTo(buf); err != nil {
		return nil, err
	}
	return buf, nil
}

const defaultStylesheet = `/* Shelf ePub Stylesheet */

body {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 1em;
  line-height: 1.6;
  margin: 1em;
  text-align: justify;
}

h1, h2, h3, h4, h5, h6 {
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-weight: bold;
  margin-top: 1.5em;
  margin-bottom: 0.5em;
  text-align: left;
}

h1 {
  font-size: 1.8em;
  border-bottom: 1px solid #ccc;
  padding-bottom: 0.3em;
}

h2 {
  font-size: 1.4em;
}

h3 {
  font-size: 1.2em;
}

p {
  margin: 0.5em 0;
  text-indent: 1.5em;
}

p:first-of-type,
h1 + p, h2 + p, h3 + p {
  text-indent: 0;
}

blockquote {
  margin: 1em 2em;
  font-style: italic;
  border-left: 3px solid #ccc;
  padding-left: 1em;
}

.chapter-title {
  text-align: center;
  margin-top: 3em;
  margin-bottom: 2em;
}

.chapter-number {
  font-size: 0.9em;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 0.5em;
}

.front-matter, .back-matter {
  font-size: 0.95em;
}

.notes {
  font-size: 0.85em;
}
`
