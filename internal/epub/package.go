package epub

import (
	"fmt"
	"strings"
	"time"
)

// generatePackage creates the content.opf package document.
func (b *Builder) generatePackage() string {
	var sb strings.Builder

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

	sb.WriteString("  </metadata>\n\n")

	// Manifest
	sb.WriteString("  <manifest>\n")
	sb.WriteString("    <item id=\"nav\" href=\"nav.xhtml\" media-type=\"application/xhtml+xml\" properties=\"nav\"/>\n")
	sb.WriteString("    <item id=\"ncx\" href=\"toc.ncx\" media-type=\"application/x-dtbncx+xml\"/>\n")
	sb.WriteString("    <item id=\"style\" href=\"styles/style.css\" media-type=\"text/css\"/>\n")

	// Chapter items
	for _, ch := range b.chapters {
		sb.WriteString(fmt.Sprintf("    <item id=\"%s\" href=\"chapters/%s.xhtml\" media-type=\"application/xhtml+xml\"/>\n",
			ch.ID, ch.ID))
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

// escapeXML escapes special XML characters.
func escapeXML(s string) string {
	s = strings.ReplaceAll(s, "&", "&amp;")
	s = strings.ReplaceAll(s, "<", "&lt;")
	s = strings.ReplaceAll(s, ">", "&gt;")
	s = strings.ReplaceAll(s, "\"", "&quot;")
	s = strings.ReplaceAll(s, "'", "&apos;")
	return s
}
