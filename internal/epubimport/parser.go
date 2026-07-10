// Package epubimport parses EPUB publications into Shelf's finished chapter
// representation. EPUB text is already the source of truth, so this path does
// not route content through scan extraction, OCR, or LLM structure stages.
package epubimport

import (
	"archive/zip"
	"encoding/xml"
	"fmt"
	"io"
	"net/url"
	"path"
	"sort"
	"strconv"
	"strings"
	"unicode"

	nethtml "golang.org/x/net/html"
)

const maxContentDocumentBytes = 32 << 20

// Publication is the source-backed representation extracted from an EPUB.
type Publication struct {
	Title       string
	Authors     []string
	Language    string
	Identifier  string
	Publisher   string
	Description string
	Subjects    []string
	Chapters    []Chapter
}

// Chapter is one terminal Shelf chapter derived from EPUB navigation/spine.
type Chapter struct {
	Title        string
	Level        int
	SourceHref   string
	MatterType   string
	ContentType  string
	AudioInclude bool
	Markdown     string
	Paragraphs   []string
}

type containerDocument struct {
	Rootfiles []struct {
		FullPath string `xml:"full-path,attr"`
	} `xml:"rootfiles>rootfile"`
}

type packageDocument struct {
	Metadata struct {
		Titles       []string `xml:"title"`
		Creators     []string `xml:"creator"`
		Languages    []string `xml:"language"`
		Identifiers  []string `xml:"identifier"`
		Publishers   []string `xml:"publisher"`
		Descriptions []string `xml:"description"`
		Subjects     []string `xml:"subject"`
	} `xml:"metadata"`
	Manifest struct {
		Items []manifestItem `xml:"item"`
	} `xml:"manifest"`
	Spine struct {
		TOC      string     `xml:"toc,attr"`
		Itemrefs []spineRef `xml:"itemref"`
	} `xml:"spine"`
}

type manifestItem struct {
	ID         string `xml:"id,attr"`
	Href       string `xml:"href,attr"`
	MediaType  string `xml:"media-type,attr"`
	Properties string `xml:"properties,attr"`
}

type spineRef struct {
	IDRef  string `xml:"idref,attr"`
	Linear string `xml:"linear,attr"`
}

type navEntry struct {
	Title    string
	DocPath  string
	Fragment string
	Level    int
}

type contentBlock struct {
	ID    string
	Kind  string
	Level int
	Text  string
}

// Parse reads and validates an EPUB before any Shelf state is mutated.
func Parse(filename string) (*Publication, error) {
	zr, err := zip.OpenReader(filename)
	if err != nil {
		return nil, fmt.Errorf("open EPUB archive: %w", err)
	}
	defer zr.Close()

	files := make(map[string]*zip.File, len(zr.File))
	for _, file := range zr.File {
		name, err := cleanArchivePath(file.Name)
		if err != nil {
			return nil, err
		}
		files[name] = file
	}

	containerBytes, err := readArchiveFile(files, "META-INF/container.xml")
	if err != nil {
		return nil, fmt.Errorf("read EPUB container: %w", err)
	}
	var container containerDocument
	if err := xml.Unmarshal(containerBytes, &container); err != nil {
		return nil, fmt.Errorf("parse EPUB container: %w", err)
	}
	if len(container.Rootfiles) == 0 || strings.TrimSpace(container.Rootfiles[0].FullPath) == "" {
		return nil, fmt.Errorf("EPUB container has no package rootfile")
	}
	opfPath, err := cleanArchivePath(container.Rootfiles[0].FullPath)
	if err != nil {
		return nil, fmt.Errorf("invalid EPUB package path: %w", err)
	}
	opfBytes, err := readArchiveFile(files, opfPath)
	if err != nil {
		return nil, fmt.Errorf("read EPUB package %s: %w", opfPath, err)
	}
	var pkg packageDocument
	if err := xml.Unmarshal(opfBytes, &pkg); err != nil {
		return nil, fmt.Errorf("parse EPUB package %s: %w", opfPath, err)
	}

	publication := &Publication{
		Title:       firstNonEmpty(pkg.Metadata.Titles),
		Authors:     cleanStrings(pkg.Metadata.Creators),
		Language:    firstNonEmpty(pkg.Metadata.Languages),
		Identifier:  firstNonEmpty(pkg.Metadata.Identifiers),
		Publisher:   firstNonEmpty(pkg.Metadata.Publishers),
		Description: firstNonEmpty(pkg.Metadata.Descriptions),
		Subjects:    cleanStrings(pkg.Metadata.Subjects),
	}
	if publication.Title == "" {
		return nil, fmt.Errorf("EPUB package has no title")
	}
	if publication.Language == "" {
		publication.Language = "en"
	}

	manifest := make(map[string]manifestItem, len(pkg.Manifest.Items))
	var navItem *manifestItem
	for i := range pkg.Manifest.Items {
		item := pkg.Manifest.Items[i]
		manifest[item.ID] = item
		if hasToken(item.Properties, "nav") {
			navItem = &item
		}
	}
	if len(pkg.Spine.Itemrefs) == 0 {
		return nil, fmt.Errorf("EPUB package has an empty spine")
	}

	baseDir := path.Dir(opfPath)
	var navigation []navEntry
	if navItem != nil {
		navPath, err := resolveArchiveReference(baseDir, navItem.Href)
		if err != nil {
			return nil, fmt.Errorf("resolve EPUB navigation document: %w", err)
		}
		if navBytes, readErr := readArchiveFile(files, navPath); readErr == nil {
			navigation, err = parseNavDocument(navBytes, navPath)
			if err != nil {
				return nil, fmt.Errorf("parse EPUB navigation document: %w", err)
			}
		}
	}
	if len(navigation) == 0 && pkg.Spine.TOC != "" {
		if item, ok := manifest[pkg.Spine.TOC]; ok {
			ncxPath, err := resolveArchiveReference(baseDir, item.Href)
			if err != nil {
				return nil, fmt.Errorf("resolve EPUB NCX: %w", err)
			}
			if ncxBytes, readErr := readArchiveFile(files, ncxPath); readErr == nil {
				navigation, err = parseNCX(ncxBytes, ncxPath)
				if err != nil {
					return nil, fmt.Errorf("parse EPUB NCX: %w", err)
				}
			}
		}
	}

	for _, ref := range pkg.Spine.Itemrefs {
		if strings.EqualFold(ref.Linear, "no") {
			continue
		}
		item, ok := manifest[ref.IDRef]
		if !ok {
			return nil, fmt.Errorf("EPUB spine references missing manifest item %q", ref.IDRef)
		}
		if hasToken(item.Properties, "nav") || !isContentDocument(item) {
			continue
		}
		docPath, err := resolveArchiveReference(baseDir, item.Href)
		if err != nil {
			return nil, fmt.Errorf("resolve EPUB spine item %q: %w", item.Href, err)
		}
		content, err := readArchiveFile(files, docPath)
		if err != nil {
			return nil, fmt.Errorf("read EPUB spine item %s: %w", docPath, err)
		}
		if len(content) > maxContentDocumentBytes {
			return nil, fmt.Errorf("EPUB content document %s exceeds %d bytes", docPath, maxContentDocumentBytes)
		}
		chapters, err := parseContentDocument(content, docPath, navigation)
		if err != nil {
			return nil, fmt.Errorf("parse EPUB spine item %s: %w", docPath, err)
		}
		publication.Chapters = append(publication.Chapters, chapters...)
	}

	filtered := publication.Chapters[:0]
	for _, chapter := range publication.Chapters {
		chapter.Markdown = strings.TrimSpace(chapter.Markdown)
		if len([]rune(chapter.Markdown)) < 20 {
			continue
		}
		filtered = append(filtered, chapter)
	}
	publication.Chapters = filtered
	if len(publication.Chapters) == 0 {
		return nil, fmt.Errorf("EPUB contains no usable linear text; it may be encrypted or image-only")
	}
	return publication, nil
}

func readArchiveFile(files map[string]*zip.File, name string) ([]byte, error) {
	file := files[name]
	if file == nil {
		return nil, fmt.Errorf("archive member %q not found", name)
	}
	r, err := file.Open()
	if err != nil {
		return nil, err
	}
	defer r.Close()
	return io.ReadAll(io.LimitReader(r, maxContentDocumentBytes+1))
}

func cleanArchivePath(name string) (string, error) {
	name = strings.ReplaceAll(strings.TrimSpace(name), "\\", "/")
	clean := path.Clean(strings.TrimPrefix(name, "/"))
	if clean == "." || clean == "" || clean == ".." || strings.HasPrefix(clean, "../") {
		return "", fmt.Errorf("unsafe EPUB archive path %q", name)
	}
	return clean, nil
}

func resolveArchiveReference(baseDir, reference string) (string, error) {
	u, err := url.Parse(strings.TrimSpace(reference))
	if err != nil {
		return "", err
	}
	if u.Scheme != "" || u.Host != "" {
		return "", fmt.Errorf("external EPUB reference %q", reference)
	}
	refPath, err := url.PathUnescape(u.Path)
	if err != nil {
		return "", err
	}
	return cleanArchivePath(path.Join(baseDir, refPath))
}

func parseNavDocument(content []byte, navPath string) ([]navEntry, error) {
	root, err := nethtml.Parse(strings.NewReader(string(content)))
	if err != nil {
		return nil, err
	}
	var toc *nethtml.Node
	var firstNav *nethtml.Node
	var find func(*nethtml.Node)
	find = func(node *nethtml.Node) {
		if node.Type == nethtml.ElementNode && strings.EqualFold(node.Data, "nav") {
			if firstNav == nil {
				firstNav = node
			}
			for _, attr := range node.Attr {
				value := strings.ToLower(attr.Val)
				if (attr.Key == "type" || attr.Key == "role") && (strings.Contains(value, "toc") || strings.Contains(value, "doc-toc")) {
					toc = node
					return
				}
			}
		}
		for child := node.FirstChild; child != nil && toc == nil; child = child.NextSibling {
			find(child)
		}
	}
	find(root)
	if toc == nil {
		toc = firstNav
	}
	if toc == nil {
		return nil, nil
	}

	var entries []navEntry
	var walk func(*nethtml.Node, int)
	walk = func(node *nethtml.Node, listDepth int) {
		if node.Type == nethtml.ElementNode && (node.Data == "ol" || node.Data == "ul") {
			listDepth++
		}
		if node.Type == nethtml.ElementNode && node.Data == "a" {
			href := attrValue(node, "href")
			title := normalizeText(nodeText(node))
			if href != "" && title != "" {
				u, parseErr := url.Parse(href)
				if parseErr == nil && u.Scheme == "" && u.Host == "" {
					resolved, resolveErr := resolveArchiveReference(path.Dir(navPath), u.Path)
					if resolveErr == nil {
						fragment, _ := url.PathUnescape(u.Fragment)
						level := listDepth
						if level < 1 {
							level = 1
						}
						entries = append(entries, navEntry{Title: title, DocPath: resolved, Fragment: fragment, Level: level})
					}
				}
			}
		}
		for child := node.FirstChild; child != nil; child = child.NextSibling {
			walk(child, listDepth)
		}
	}
	walk(toc, 0)
	return entries, nil
}

type ncxDocument struct {
	NavPoints []ncxPoint `xml:"navMap>navPoint"`
}

type ncxPoint struct {
	Label struct {
		Text string `xml:"text"`
	} `xml:"navLabel"`
	Content struct {
		Src string `xml:"src,attr"`
	} `xml:"content"`
	Children []ncxPoint `xml:"navPoint"`
}

func parseNCX(content []byte, ncxPath string) ([]navEntry, error) {
	var ncx ncxDocument
	if err := xml.Unmarshal(content, &ncx); err != nil {
		return nil, err
	}
	var entries []navEntry
	var walk func([]ncxPoint, int)
	walk = func(points []ncxPoint, level int) {
		for _, point := range points {
			u, err := url.Parse(point.Content.Src)
			if err == nil && u.Scheme == "" && u.Host == "" {
				resolved, resolveErr := resolveArchiveReference(path.Dir(ncxPath), u.Path)
				if resolveErr == nil {
					fragment, _ := url.PathUnescape(u.Fragment)
					entries = append(entries, navEntry{
						Title: normalizeText(point.Label.Text), DocPath: resolved,
						Fragment: fragment, Level: level,
					})
				}
			}
			walk(point.Children, level+1)
		}
	}
	walk(ncx.NavPoints, 1)
	return entries, nil
}

func parseContentDocument(content []byte, docPath string, navigation []navEntry) ([]Chapter, error) {
	root, err := nethtml.Parse(strings.NewReader(string(content)))
	if err != nil {
		return nil, err
	}
	blocks := extractBlocks(root)
	if len(blocks) == 0 {
		fallback := normalizeText(nodeText(findElement(root, "body")))
		if fallback == "" {
			return nil, nil
		}
		blocks = []contentBlock{{Kind: "paragraph", Text: fallback}}
	}

	var entries []navEntry
	for _, entry := range navigation {
		if entry.DocPath == docPath {
			entries = append(entries, entry)
		}
	}
	docTitle := documentTitle(root, docPath)
	if len(entries) <= 1 {
		title := docTitle
		level := 1
		if len(entries) == 1 {
			title = entries[0].Title
			level = entries[0].Level
		}
		return []Chapter{chapterFromBlocks(title, level, docPath, blocks)}, nil
	}

	type splitPoint struct {
		entry navEntry
		index int
	}
	var points []splitPoint
	for _, entry := range entries {
		idx := 0
		if entry.Fragment != "" {
			idx = findBlockByID(blocks, entry.Fragment)
			if idx < 0 {
				idx = findHeadingByTitle(blocks, entry.Title)
			}
			if idx < 0 {
				continue
			}
		}
		points = append(points, splitPoint{entry: entry, index: idx})
	}
	if len(points) <= 1 {
		return []Chapter{chapterFromBlocks(entries[0].Title, entries[0].Level, docPath, blocks)}, nil
	}
	sort.SliceStable(points, func(i, j int) bool { return points[i].index < points[j].index })
	unique := points[:0]
	for _, point := range points {
		if len(unique) > 0 && unique[len(unique)-1].index == point.index {
			continue
		}
		unique = append(unique, point)
	}
	points = unique
	merged := points[:0]
	for i, point := range points {
		if len(merged) > 0 {
			parent := merged[len(merged)-1]
			nextReturnsToParent := i+1 >= len(points) || points[i+1].entry.Level <= parent.entry.Level
			if point.entry.Level > parent.entry.Level && nextReturnsToParent && !blocksContainProse(blocks[parent.index:point.index]) {
				continue // a sole adjacent subtitle belongs to its parent chapter
			}
		}
		merged = append(merged, point)
	}
	points = merged
	if points[0].index > 0 {
		points[0].index = 0 // keep document preamble with its first named section
	}

	chapters := make([]Chapter, 0, len(points))
	for i, point := range points {
		end := len(blocks)
		if i+1 < len(points) {
			end = points[i+1].index
		}
		if end <= point.index {
			continue
		}
		chapters = append(chapters, chapterFromBlocks(point.entry.Title, point.entry.Level, docPath+"#"+point.entry.Fragment, blocks[point.index:end]))
	}
	return chapters, nil
}

func blocksContainProse(blocks []contentBlock) bool {
	for _, block := range blocks {
		if block.Kind == "paragraph" || block.Kind == "list" {
			return true
		}
	}
	return false
}

func extractBlocks(root *nethtml.Node) []contentBlock {
	var blocks []contentBlock
	var walk func(*nethtml.Node)
	walk = func(node *nethtml.Node) {
		if node.Type == nethtml.ElementNode {
			tag := strings.ToLower(node.Data)
			switch tag {
			case "script", "style", "svg", "nav":
				return
			case "h1", "h2", "h3", "h4", "h5", "h6":
				text := normalizeText(nodeText(node))
				if text != "" {
					level, _ := strconv.Atoi(strings.TrimPrefix(tag, "h"))
					blocks = append(blocks, contentBlock{ID: descendantID(node), Kind: "heading", Level: level, Text: text})
				}
				return
			case "p", "blockquote", "pre", "figcaption":
				text := normalizeText(nodeText(node))
				if text != "" {
					blocks = append(blocks, contentBlock{ID: descendantID(node), Kind: "paragraph", Text: text})
				}
				return
			case "li":
				text := normalizeText(nodeTextWithoutNestedLists(node))
				if text != "" {
					blocks = append(blocks, contentBlock{ID: descendantID(node), Kind: "list", Text: text})
				}
				return
			}
		}
		for child := node.FirstChild; child != nil; child = child.NextSibling {
			walk(child)
		}
	}
	body := findElement(root, "body")
	if body == nil {
		body = root
	}
	walk(body)
	return blocks
}

func chapterFromBlocks(title string, level int, source string, blocks []contentBlock) Chapter {
	title = normalizeText(title)
	if title == "" {
		title = "Untitled"
	}
	if level < 1 {
		level = 1
	}
	var markdown []string
	var paragraphs []string
	for _, block := range blocks {
		switch block.Kind {
		case "heading":
			headingLevel := block.Level
			if headingLevel < 1 {
				headingLevel = 1
			}
			markdown = append(markdown, strings.Repeat("#", headingLevel)+" "+block.Text)
		case "list":
			markdown = append(markdown, "- "+block.Text)
			paragraphs = append(paragraphs, block.Text)
		default:
			markdown = append(markdown, block.Text)
			paragraphs = append(paragraphs, block.Text)
		}
	}
	matter, contentType, include := classifyChapter(title, source)
	return Chapter{
		Title: title, Level: level, SourceHref: source, MatterType: matter,
		ContentType: contentType, AudioInclude: include,
		Markdown: strings.Join(markdown, "\n\n"), Paragraphs: paragraphs,
	}
}

func classifyChapter(title, source string) (string, string, bool) {
	lower := strings.ToLower(title + " " + source)
	typeRule := func(contentType string, include bool) (string, string, bool) {
		matter := "front_matter"
		if contentType == "appendix" || contentType == "index" || contentType == "bibliography" || contentType == "glossary" || contentType == "notes" || contentType == "endnotes" || contentType == "acknowledgments" || contentType == "about_author" || contentType == "afterword" {
			matter = "back_matter"
		}
		return matter, contentType, include
	}
	for _, rule := range []struct {
		needles     []string
		contentType string
		include     bool
	}{
		{[]string{"table of contents", "contents", " toc"}, "other", false},
		{[]string{"copyright", "colophon"}, "copyright", false},
		{[]string{"project gutenberg", "license"}, "copyright", false},
		{[]string{"title page", "cover"}, "other", false},
		{[]string{"foreword"}, "foreword", true},
		{[]string{"preface"}, "preface", true},
		{[]string{"introduction"}, "introduction", true},
		{[]string{"prologue"}, "prologue", true},
		{[]string{"epilogue"}, "epilogue", true},
		{[]string{"afterword"}, "afterword", true},
		{[]string{"author's note", "authors note", "author note"}, "author_note", true},
		{[]string{"dedication"}, "dedication", true},
		{[]string{"acknowledg"}, "acknowledgments", true},
		{[]string{"about the author", "about author"}, "about_author", true},
		{[]string{"appendix"}, "appendix", true},
		{[]string{"bibliograph", "references", "suggested reading", "further reading"}, "bibliography", false},
		{[]string{"endnotes"}, "endnotes", false},
		{[]string{"notes"}, "notes", false},
		{[]string{"glossary"}, "glossary", false},
		{[]string{"index"}, "index", false},
	} {
		for _, needle := range rule.needles {
			if strings.Contains(lower, needle) {
				return typeRule(rule.contentType, rule.include)
			}
		}
	}
	return "body", "body", true
}

func documentTitle(root *nethtml.Node, docPath string) string {
	for _, tag := range []string{"h1", "h2", "h3", "title"} {
		if node := findElement(root, tag); node != nil {
			if text := normalizeText(nodeText(node)); text != "" {
				return text
			}
		}
	}
	base := path.Base(docPath)
	return strings.TrimSuffix(base, path.Ext(base))
}

func findBlockByID(blocks []contentBlock, id string) int {
	for i, block := range blocks {
		if block.ID == id {
			return i
		}
	}
	return -1
}

func findHeadingByTitle(blocks []contentBlock, title string) int {
	want := comparableText(title)
	for i, block := range blocks {
		if block.Kind == "heading" && comparableText(block.Text) == want {
			return i
		}
	}
	return -1
}

func comparableText(value string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			return unicode.ToLower(r)
		}
		return -1
	}, value)
}

func findElement(root *nethtml.Node, tag string) *nethtml.Node {
	if root == nil {
		return nil
	}
	if root.Type == nethtml.ElementNode && strings.EqualFold(root.Data, tag) {
		return root
	}
	for child := root.FirstChild; child != nil; child = child.NextSibling {
		if found := findElement(child, tag); found != nil {
			return found
		}
	}
	return nil
}

func descendantID(node *nethtml.Node) string {
	if node == nil {
		return ""
	}
	if value := attrValue(node, "id"); value != "" {
		return value
	}
	if node.Type == nethtml.ElementNode && node.Data == "a" {
		if value := attrValue(node, "name"); value != "" {
			return value
		}
	}
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		if value := descendantID(child); value != "" {
			return value
		}
	}
	return ""
}

func attrValue(node *nethtml.Node, key string) string {
	for _, attr := range node.Attr {
		if strings.EqualFold(attr.Key, key) {
			return strings.TrimSpace(attr.Val)
		}
	}
	return ""
}

func nodeText(node *nethtml.Node) string {
	if node == nil {
		return ""
	}
	if node.Type == nethtml.TextNode {
		return node.Data
	}
	var b strings.Builder
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		if child.Type == nethtml.ElementNode && child.Data == "br" {
			b.WriteByte(' ')
			continue
		}
		b.WriteString(nodeText(child))
		b.WriteByte(' ')
	}
	return b.String()
}

func nodeTextWithoutNestedLists(node *nethtml.Node) string {
	if node == nil {
		return ""
	}
	if node.Type == nethtml.TextNode {
		return node.Data
	}
	var b strings.Builder
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		if child.Type == nethtml.ElementNode && (child.Data == "ol" || child.Data == "ul") {
			continue
		}
		b.WriteString(nodeTextWithoutNestedLists(child))
		b.WriteByte(' ')
	}
	return b.String()
}

func normalizeText(value string) string { return strings.Join(strings.Fields(value), " ") }

func firstNonEmpty(values []string) string {
	for _, value := range values {
		if value = normalizeText(value); value != "" {
			return value
		}
	}
	return ""
}

func cleanStrings(values []string) []string {
	var clean []string
	seen := make(map[string]struct{})
	for _, value := range values {
		value = normalizeText(value)
		if value == "" {
			continue
		}
		if _, ok := seen[value]; ok {
			continue
		}
		seen[value] = struct{}{}
		clean = append(clean, value)
	}
	return clean
}

func hasToken(value, token string) bool {
	for _, field := range strings.Fields(value) {
		if strings.EqualFold(field, token) {
			return true
		}
	}
	return false
}

func isContentDocument(item manifestItem) bool {
	media := strings.ToLower(item.MediaType)
	return media == "application/xhtml+xml" || media == "text/html" || strings.HasSuffix(strings.ToLower(item.Href), ".xhtml") || strings.HasSuffix(strings.ToLower(item.Href), ".html") || strings.HasSuffix(strings.ToLower(item.Href), ".htm")
}
