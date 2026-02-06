package epub

import (
	"archive/zip"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
)

// MediaOverlayBuilder creates EPUB3 files with Media Overlays (synced audio).
type MediaOverlayBuilder struct {
	book          Book
	chapters      []Chapter
	chapterAudios map[string]ChapterAudio // keyed by chapter ID
	narrator      string                   // Optional narrator name
	coverImage    string                   // Optional path to cover image file
}

// NewMediaOverlayBuilder creates a new builder for EPUBs with audio sync.
func NewMediaOverlayBuilder(book Book, chapters []Chapter) *MediaOverlayBuilder {
	return &MediaOverlayBuilder{
		book:          book,
		chapters:      chapters,
		chapterAudios: make(map[string]ChapterAudio),
	}
}

// SetNarrator sets the narrator metadata.
func (b *MediaOverlayBuilder) SetNarrator(name string) {
	b.narrator = name
}

// SetCoverImage sets the path to a cover image file (PNG or JPEG).
func (b *MediaOverlayBuilder) SetCoverImage(path string) {
	b.coverImage = path
}

// AddChapterAudio adds audio timing data for a chapter.
func (b *MediaOverlayBuilder) AddChapterAudio(chapterID string, audio ChapterAudio) {
	b.chapterAudios[chapterID] = audio
}

// Build generates the EPUB with Media Overlays and writes to the specified path.
func (b *MediaOverlayBuilder) Build(outputPath string) error {
	if err := os.MkdirAll(filepath.Dir(outputPath), 0755); err != nil {
		return fmt.Errorf("failed to create output directory: %w", err)
	}

	f, err := os.Create(outputPath)
	if err != nil {
		return fmt.Errorf("failed to create output file: %w", err)
	}
	defer f.Close()

	return b.WriteTo(f)
}

// WriteTo writes the EPUB with Media Overlays to a writer.
func (b *MediaOverlayBuilder) WriteTo(w io.Writer) error {
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

	// 3. Write OEBPS/content.opf (package document with media overlay refs)
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

	// 7. Write chapter XHTML files (with paragraph IDs)
	for _, ch := range b.chapters {
		if err := b.writeChapter(zw, ch); err != nil {
			return fmt.Errorf("failed to write chapter %s: %w", ch.ID, err)
		}
	}

	// 8. Write SMIL files for chapters with audio
	for _, ch := range b.chapters {
		if audio, ok := b.chapterAudios[ch.ID]; ok {
			if err := b.writeSMIL(zw, ch.ID, audio); err != nil {
				return fmt.Errorf("failed to write SMIL for %s: %w", ch.ID, err)
			}
		}
	}

	// 9. Write audio files
	for _, ch := range b.chapters {
		if audio, ok := b.chapterAudios[ch.ID]; ok {
			if err := b.writeAudioFile(zw, audio); err != nil {
				return fmt.Errorf("failed to write audio for %s: %w", ch.ID, err)
			}
		}
	}

	// 10. Write cover image if provided
	if b.coverImage != "" {
		if err := b.writeCoverImage(zw); err != nil {
			return fmt.Errorf("failed to write cover image: %w", err)
		}
	}

	return nil
}

func (b *MediaOverlayBuilder) writeMimetype(zw *zip.Writer) error {
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

func (b *MediaOverlayBuilder) writeContainer(zw *zip.Writer) error {
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

func (b *MediaOverlayBuilder) writePackage(zw *zip.Writer) error {
	w, err := zw.Create("OEBPS/content.opf")
	if err != nil {
		return fmt.Errorf("failed to create content.opf: %w", err)
	}

	content := b.generatePackage()
	_, err = w.Write([]byte(content))
	return err
}

func (b *MediaOverlayBuilder) generatePackage() string {
	var sb strings.Builder

	// Calculate total duration
	var totalDurationMS int
	for _, audio := range b.chapterAudios {
		totalDurationMS += audio.DurationMS
	}

	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
`)

	// Dublin Core metadata
	sb.WriteString(fmt.Sprintf("    <dc:identifier id=\"pub-id\">%s</dc:identifier>\n", b.generateUUID()))
	sb.WriteString(fmt.Sprintf("    <dc:title>%s</dc:title>\n", escapeXML(b.book.Title)))
	sb.WriteString(fmt.Sprintf("    <dc:creator>%s</dc:creator>\n", escapeXML(b.book.Author)))

	lang := b.book.Language
	if lang == "" {
		lang = "en"
	}
	sb.WriteString(fmt.Sprintf("    <dc:language>%s</dc:language>\n", lang))

	if b.book.Publisher != "" {
		sb.WriteString(fmt.Sprintf("    <dc:publisher>%s</dc:publisher>\n", escapeXML(b.book.Publisher)))
	}

	// Modified timestamp (required for ePub 3)
	sb.WriteString(fmt.Sprintf("    <meta property=\"dcterms:modified\">%s</meta>\n",
		time.Now().UTC().Format("2006-01-02T15:04:05Z")))

	// Media Overlay metadata
	if totalDurationMS > 0 {
		sb.WriteString(fmt.Sprintf("    <meta property=\"media:duration\">%s</meta>\n",
			formatClockTime(totalDurationMS)))
		sb.WriteString("    <meta property=\"media:active-class\">-epub-media-overlay-active</meta>\n")
	}

	// Cover image meta (EPUB 2 compatibility)
	if b.coverImage != "" {
		sb.WriteString("    <meta name=\"cover\" content=\"cover-image\"/>\n")
	}

	// Narrator
	if b.narrator != "" {
		sb.WriteString(fmt.Sprintf("    <meta property=\"media:narrator\">%s</meta>\n", escapeXML(b.narrator)))
	}

	sb.WriteString("  </metadata>\n\n")

	// Manifest
	sb.WriteString("  <manifest>\n")
	sb.WriteString("    <item id=\"nav\" href=\"nav.xhtml\" media-type=\"application/xhtml+xml\" properties=\"nav\"/>\n")
	sb.WriteString("    <item id=\"ncx\" href=\"toc.ncx\" media-type=\"application/x-dtbncx+xml\"/>\n")
	sb.WriteString("    <item id=\"style\" href=\"styles/style.css\" media-type=\"text/css\"/>\n")

	// Cover image
	if b.coverImage != "" {
		ext := strings.ToLower(filepath.Ext(b.coverImage))
		sb.WriteString(fmt.Sprintf("    <item id=\"cover-image\" href=\"images/cover%s\" media-type=\"%s\" properties=\"cover-image\"/>\n",
			ext, coverMediaType(b.coverImage)))
	}

	// Chapter items with media-overlay reference
	for _, ch := range b.chapters {
		if _, hasAudio := b.chapterAudios[ch.ID]; hasAudio {
			sb.WriteString(fmt.Sprintf("    <item id=\"%s\" href=\"chapters/%s.xhtml\" media-type=\"application/xhtml+xml\" media-overlay=\"%s_overlay\"/>\n",
				ch.ID, ch.ID, ch.ID))
		} else {
			sb.WriteString(fmt.Sprintf("    <item id=\"%s\" href=\"chapters/%s.xhtml\" media-type=\"application/xhtml+xml\"/>\n",
				ch.ID, ch.ID))
		}
	}

	// SMIL items
	for _, ch := range b.chapters {
		if audio, hasAudio := b.chapterAudios[ch.ID]; hasAudio {
			sb.WriteString(fmt.Sprintf("    <item id=\"%s_overlay\" href=\"smil/%s.smil\" media-type=\"application/smil+xml\" duration=\"%s\"/>\n",
				ch.ID, ch.ID, formatClockTime(audio.DurationMS)))
		}
	}

	// Audio items
	for _, ch := range b.chapters {
		if audio, hasAudio := b.chapterAudios[ch.ID]; hasAudio {
			audioFilename := filepath.Base(audio.AudioFile)
			sb.WriteString(fmt.Sprintf("    <item id=\"%s_audio\" href=\"audio/%s\" media-type=\"audio/mpeg\"/>\n",
				ch.ID, audioFilename))
		}
	}

	sb.WriteString("  </manifest>\n\n")

	// Spine (reading order)
	sb.WriteString("  <spine toc=\"ncx\">\n")
	for _, ch := range b.chapters {
		sb.WriteString(fmt.Sprintf("    <itemref idref=\"%s\"/>\n", ch.ID))
	}
	sb.WriteString("  </spine>\n")

	sb.WriteString("</package>\n")

	return sb.String()
}

func (b *MediaOverlayBuilder) writeNavigation(zw *zip.Writer) error {
	w, err := zw.Create("OEBPS/nav.xhtml")
	if err != nil {
		return fmt.Errorf("failed to create nav.xhtml: %w", err)
	}

	// Reuse navigation generation from base builder
	base := &Builder{book: b.book, chapters: b.chapters}
	content := base.generateNavigation()
	_, err = w.Write([]byte(content))
	return err
}

func (b *MediaOverlayBuilder) writeNCX(zw *zip.Writer) error {
	w, err := zw.Create("OEBPS/toc.ncx")
	if err != nil {
		return fmt.Errorf("failed to create toc.ncx: %w", err)
	}

	base := &Builder{book: b.book, chapters: b.chapters}
	content := base.generateNCX()
	_, err = w.Write([]byte(content))
	return err
}

func (b *MediaOverlayBuilder) writeStylesheet(zw *zip.Writer) error {
	w, err := zw.Create("OEBPS/styles/style.css")
	if err != nil {
		return fmt.Errorf("failed to create style.css: %w", err)
	}

	// Add media overlay active class styling
	stylesheet := defaultStylesheet + `

/* Media Overlay active text highlighting */
.-epub-media-overlay-active {
  background-color: #ffffcc;
}
`
	_, err = w.Write([]byte(stylesheet))
	return err
}

func (b *MediaOverlayBuilder) writeChapter(zw *zip.Writer, ch Chapter) error {
	filename := fmt.Sprintf("OEBPS/chapters/%s.xhtml", ch.ID)
	w, err := zw.Create(filename)
	if err != nil {
		return fmt.Errorf("failed to create %s: %w", filename, err)
	}

	// Use XHTML with paragraph IDs for SMIL reference
	content := b.generateChapterXHTML(ch)
	_, err = w.Write([]byte(content))
	return err
}

func (b *MediaOverlayBuilder) generateChapterXHTML(ch Chapter) string {
	var sb strings.Builder

	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>`)
	sb.WriteString(escapeXML(ch.Title))
	sb.WriteString(`</title>
  <link rel="stylesheet" type="text/css" href="../styles/style.css"/>
</head>
<body`)

	switch ch.MatterType {
	case "front_matter":
		sb.WriteString(` class="front-matter"`)
	case "back_matter":
		sb.WriteString(` class="back-matter"`)
		if ch.LevelName == "notes" {
			sb.WriteString(` class="back-matter notes"`)
		}
	}
	sb.WriteString(">\n")

	// Convert markdown to XHTML with paragraph IDs
	content := markdownToXHTMLWithIDs(ch.PolishedText, ch, true)
	sb.WriteString(content)

	sb.WriteString("\n</body>\n</html>\n")

	return sb.String()
}

func (b *MediaOverlayBuilder) writeSMIL(zw *zip.Writer, chapterID string, audio ChapterAudio) error {
	filename := fmt.Sprintf("OEBPS/smil/%s.smil", chapterID)
	w, err := zw.Create(filename)
	if err != nil {
		return fmt.Errorf("failed to create %s: %w", filename, err)
	}

	// Update audio file path to be relative within EPUB
	audioInEpub := ChapterAudio{
		ChapterID:  audio.ChapterID,
		AudioFile:  fmt.Sprintf("../audio/%s", filepath.Base(audio.AudioFile)),
		DurationMS: audio.DurationMS,
		Segments:   audio.Segments,
	}

	content := generateSMIL(chapterID, audioInEpub)
	_, err = w.Write([]byte(content))
	return err
}

func (b *MediaOverlayBuilder) writeAudioFile(zw *zip.Writer, audio ChapterAudio) error {
	audioFilename := filepath.Base(audio.AudioFile)
	destPath := fmt.Sprintf("OEBPS/audio/%s", audioFilename)

	// Read source audio file
	data, err := os.ReadFile(audio.AudioFile)
	if err != nil {
		return fmt.Errorf("failed to read audio file %s: %w", audio.AudioFile, err)
	}

	// Write to EPUB (use Store method for audio - no compression benefit)
	header := &zip.FileHeader{
		Name:   destPath,
		Method: zip.Store,
	}
	w, err := zw.CreateHeader(header)
	if err != nil {
		return fmt.Errorf("failed to create %s in epub: %w", destPath, err)
	}

	_, err = w.Write(data)
	return err
}

func (b *MediaOverlayBuilder) writeCoverImage(zw *zip.Writer) error {
	data, err := os.ReadFile(b.coverImage)
	if err != nil {
		return fmt.Errorf("failed to read cover image %s: %w", b.coverImage, err)
	}

	ext := strings.ToLower(filepath.Ext(b.coverImage))
	destPath := fmt.Sprintf("OEBPS/images/cover%s", ext)

	w, err := zw.Create(destPath)
	if err != nil {
		return fmt.Errorf("failed to create %s in epub: %w", destPath, err)
	}
	_, err = w.Write(data)
	return err
}

// coverMediaType returns the MIME type for the cover image based on extension.
func coverMediaType(path string) string {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".jpg", ".jpeg":
		return "image/jpeg"
	case ".png":
		return "image/png"
	case ".gif":
		return "image/gif"
	case ".webp":
		return "image/webp"
	default:
		return "image/png"
	}
}

func (b *MediaOverlayBuilder) generateUUID() string {
	if b.book.ISBN != "" {
		return "urn:isbn:" + b.book.ISBN
	}
	return "urn:uuid:" + uuid.New().String()
}

// formatClockTime converts milliseconds to SMIL clock time (HH:MM:SS.mmm).
func formatClockTime(ms int) string {
	hours := ms / 3600000
	minutes := (ms % 3600000) / 60000
	seconds := (ms % 60000) / 1000
	millis := ms % 1000
	return fmt.Sprintf("%02d:%02d:%02d.%03d", hours, minutes, seconds, millis)
}
