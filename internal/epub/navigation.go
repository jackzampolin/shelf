package epub

import (
	"fmt"
	"strings"
)

// generateNavigation creates the nav.xhtml navigation document.
func (b *Builder) generateNavigation() string {
	var sb strings.Builder

	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Table of Contents</title>
  <link rel="stylesheet" type="text/css" href="styles/style.css"/>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Table of Contents</h1>
    <ol>
`)

	// Group chapters by matter type for better organization
	var frontMatter, body, backMatter []Chapter
	for _, ch := range b.chapters {
		switch ch.MatterType {
		case "front_matter":
			frontMatter = append(frontMatter, ch)
		case "back_matter":
			backMatter = append(backMatter, ch)
		default:
			body = append(body, ch)
		}
	}

	// Write front matter
	for _, ch := range frontMatter {
		sb.WriteString(b.navEntry(ch))
	}

	// Write body - handle nested structure (parts containing chapters)
	b.writeNavBody(&sb, body)

	// Write back matter
	for _, ch := range backMatter {
		sb.WriteString(b.navEntry(ch))
	}

	sb.WriteString(`    </ol>
  </nav>
</body>
</html>
`)

	return sb.String()
}

// writeNavBody handles potentially nested body content.
func (b *Builder) writeNavBody(sb *strings.Builder, chapters []Chapter) {
	var i int
	for i < len(chapters) {
		ch := chapters[i]

		// Parts (level 1) may contain chapters (level 2)
		if ch.Level == 1 && ch.LevelName == "part" {
			sb.WriteString(fmt.Sprintf("      <li>\n        <a href=\"chapters/%s.xhtml\">%s</a>\n",
				ch.ID, escapeXML(b.formatTitle(ch))))

			// Collect nested chapters
			var nested []Chapter
			j := i + 1
			for j < len(chapters) && chapters[j].Level > 1 {
				nested = append(nested, chapters[j])
				j++
			}

			if len(nested) > 0 {
				sb.WriteString("        <ol>\n")
				for _, nch := range nested {
					sb.WriteString("          ")
					sb.WriteString(b.navEntry(nch))
				}
				sb.WriteString("        </ol>\n")
			}

			sb.WriteString("      </li>\n")
			i = j
		} else {
			sb.WriteString(b.navEntry(ch))
			i++
		}
	}
}

// navEntry creates a single navigation entry.
func (b *Builder) navEntry(ch Chapter) string {
	return fmt.Sprintf("      <li><a href=\"chapters/%s.xhtml\">%s</a></li>\n",
		ch.ID, escapeXML(b.formatTitle(ch)))
}

// formatTitle formats a chapter title for display.
func (b *Builder) formatTitle(ch Chapter) string {
	// For numbered chapters, include the number
	if ch.EntryNumber != "" && (ch.LevelName == "chapter" || ch.LevelName == "part") {
		prefix := ch.LevelName
		if prefix == "chapter" {
			prefix = "Chapter"
		} else if prefix == "part" {
			prefix = "Part"
		}
		// If title is just "Chapter N", don't duplicate
		if ch.Title == fmt.Sprintf("Chapter %s", ch.EntryNumber) {
			return ch.Title
		}
		if ch.Title == fmt.Sprintf("Part %s", ch.EntryNumber) {
			return ch.Title
		}
		return fmt.Sprintf("%s %s: %s", prefix, ch.EntryNumber, ch.Title)
	}
	return ch.Title
}

// generateNCX creates the toc.ncx for ePub 2 compatibility.
func (b *Builder) generateNCX() string {
	var sb strings.Builder

	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="`)
	sb.WriteString(b.generateUUID())
	sb.WriteString(`"/>
    <meta name="dtb:depth" content="2"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle>
    <text>`)
	sb.WriteString(escapeXML(b.book.Title))
	sb.WriteString(`</text>
  </docTitle>
  <navMap>
`)

	// Write nav points
	for i, ch := range b.chapters {
		sb.WriteString(fmt.Sprintf("    <navPoint id=\"navpoint-%d\" playOrder=\"%d\">\n", i+1, i+1))
		sb.WriteString(fmt.Sprintf("      <navLabel><text>%s</text></navLabel>\n", escapeXML(b.formatTitle(ch))))
		sb.WriteString(fmt.Sprintf("      <content src=\"chapters/%s.xhtml\"/>\n", ch.ID))
		sb.WriteString("    </navPoint>\n")
	}

	sb.WriteString(`  </navMap>
</ncx>
`)

	return sb.String()
}
