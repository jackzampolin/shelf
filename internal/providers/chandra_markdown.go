package providers

import (
	"fmt"
	"regexp"
	"strings"

	stdhtml "html"

	nethtml "golang.org/x/net/html"
)

func renderChandraMarkdownChildren(node *nethtml.Node) string {
	if node == nil {
		return ""
	}
	var parts []string
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		parts = append(parts, renderChandraMarkdownNode(child))
	}
	return cleanMarkdownSpacing(strings.Join(parts, ""))
}

func renderChandraMarkdownNode(node *nethtml.Node) string {
	if node == nil {
		return ""
	}
	switch node.Type {
	case nethtml.TextNode:
		return stdhtml.UnescapeString(node.Data)
	case nethtml.ElementNode:
		tag := strings.ToLower(node.Data)
		switch tag {
		case "br":
			return "  \n"
		case "p":
			return strings.TrimSpace(renderChandraMarkdownChildren(node)) + "\n\n"
		case "h1", "h2", "h3", "h4", "h5", "h6":
			level := int(tag[1] - '0')
			return strings.Repeat("#", level) + " " + strings.TrimSpace(stripMarkdownEmphasis(renderChandraMarkdownChildren(node))) + "\n\n"
		case "i", "em":
			text := strings.TrimSpace(renderChandraMarkdownChildren(node))
			if text == "" {
				return ""
			}
			return "*" + text + "*"
		case "b", "strong":
			text := strings.TrimSpace(renderChandraMarkdownChildren(node))
			if text == "" {
				return ""
			}
			return "**" + text + "**"
		case "sup", "sub", "math", "chem":
			text := strings.TrimSpace(renderChandraMarkdownChildren(node))
			if text == "" {
				return ""
			}
			return "<" + tag + ">" + text + "</" + tag + ">"
		case "ul", "ol":
			return renderListMarkdown(node, tag == "ol") + "\n"
		case "li":
			return strings.TrimSpace(renderChandraMarkdownChildren(node))
		case "pre":
			return "```\n" + strings.TrimSpace(textContent(node)) + "\n```\n\n"
		case "code":
			return "`" + strings.TrimSpace(textContent(node)) + "`"
		case "table":
			return "\n\n" + renderCleanHTML(node) + "\n\n"
		case "img":
			alt := attrValue(node, "alt")
			src := attrValue(node, "src")
			if src == "" {
				return strings.TrimSpace(alt)
			}
			return fmt.Sprintf("![%s](%s)", escapeMarkdownAlt(alt), src)
		default:
			return renderChandraMarkdownChildren(node)
		}
	default:
		return ""
	}
}

func renderListMarkdown(node *nethtml.Node, ordered bool) string {
	var lines []string
	idx := 1
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		if child.Type != nethtml.ElementNode || strings.ToLower(child.Data) != "li" {
			continue
		}
		prefix := "- "
		if ordered {
			prefix = fmt.Sprintf("%d. ", idx)
			idx++
		}
		lines = append(lines, prefix+strings.TrimSpace(renderChandraMarkdownChildren(child)))
	}
	return strings.Join(lines, "\n")
}

func cleanMarkdownSpacing(text string) string {
	text = strings.ReplaceAll(text, "\r\n", "\n")
	text = strings.ReplaceAll(text, "\r", "\n")
	spaceRe := regexp.MustCompile(`[ \t]+`)
	lines := strings.Split(text, "\n")
	for i, line := range lines {
		lines[i] = strings.TrimRight(spaceRe.ReplaceAllString(line, " "), " ")
	}
	text = strings.Join(lines, "\n")
	blankRe := regexp.MustCompile(`\n{3,}`)
	return strings.TrimSpace(blankRe.ReplaceAllString(text, "\n\n"))
}

func joinMarkdownBlocks(parts []string) string {
	cleaned := make([]string, 0, len(parts))
	for _, part := range parts {
		part = cleanMarkdownSpacing(part)
		if part != "" {
			cleaned = append(cleaned, part)
		}
	}
	return strings.Join(cleaned, "\n\n")
}

func renderCleanHTML(node *nethtml.Node) string {
	var b strings.Builder
	renderCleanHTMLNode(&b, node)
	return b.String()
}

func renderCleanHTMLNode(b *strings.Builder, node *nethtml.Node) {
	if node == nil {
		return
	}
	switch node.Type {
	case nethtml.TextNode:
		b.WriteString(escapeHTMLText(stdhtml.UnescapeString(node.Data)))
	case nethtml.ElementNode:
		tag := strings.ToLower(node.Data)
		b.WriteByte('<')
		b.WriteString(tag)
		for _, attr := range node.Attr {
			key := strings.ToLower(attr.Key)
			if strings.HasPrefix(key, "data-") || key == "class" || key == "style" {
				continue
			}
			b.WriteByte(' ')
			b.WriteString(key)
			b.WriteString(`="`)
			b.WriteString(stdhtml.EscapeString(attr.Val))
			b.WriteByte('"')
		}
		b.WriteByte('>')
		for child := node.FirstChild; child != nil; child = child.NextSibling {
			renderCleanHTMLNode(b, child)
		}
		b.WriteString("</")
		b.WriteString(tag)
		b.WriteByte('>')
	}
}

func escapeHTMLText(text string) string {
	text = strings.ReplaceAll(text, "&", "&amp;")
	text = strings.ReplaceAll(text, "<", "&lt;")
	text = strings.ReplaceAll(text, ">", "&gt;")
	return text
}

func stripMarkdownEmphasis(text string) string {
	text = strings.TrimSpace(text)
	text = strings.Trim(text, "*_")
	return strings.TrimSpace(text)
}

func escapeMarkdownAlt(text string) string {
	replacer := strings.NewReplacer("[", `\[`, "]", `\]`, "\n", " ")
	return replacer.Replace(strings.Join(strings.Fields(text), " "))
}
