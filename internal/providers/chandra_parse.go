package providers

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"image"
	"image/jpeg"
	_ "image/png"
	"regexp"
	"strconv"
	"strings"

	stdhtml "html"

	nethtml "golang.org/x/net/html"
)

type chandraParseOptions struct {
	IncludeImages         bool
	IncludeHeadersFooters bool
}

type chandraParsedPage struct {
	Markdown string
	Headers  []string
	Footers  []string
	Images   []map[string]any
}

type chandraLayoutBlock struct {
	Label string
	BBox  [4]int
	Node  *nethtml.Node
}

func parseChandraLayoutHTML(raw string, imageBytes []byte, pageNum int, opts chandraParseOptions) (chandraParsedPage, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return chandraParsedPage{}, nil
	}

	blocks, err := parseChandraLayoutBlocks(raw)
	if err != nil {
		return chandraParsedPage{}, err
	}
	if len(blocks) == 0 {
		return chandraParsedPage{Markdown: raw}, nil
	}

	var pageImage image.Image
	if opts.IncludeImages {
		pageImage, _, _ = image.Decode(bytes.NewReader(imageBytes))
	}

	var parts []string
	var headers []string
	var footers []string
	var images []map[string]any
	imageIndex := 0

	for _, block := range blocks {
		label := strings.TrimSpace(block.Label)
		blockText := strings.TrimSpace(renderChandraMarkdownChildren(block.Node))
		blockPlainText := strings.TrimSpace(textContent(block.Node))

		switch label {
		case "Blank-Page":
			continue
		case "Page-Header":
			if blockPlainText != "" {
				headers = append(headers, blockPlainText)
			}
			if !opts.IncludeHeadersFooters {
				continue
			}
		case "Page-Footer":
			if blockPlainText != "" {
				footers = append(footers, blockPlainText)
			}
			if !opts.IncludeHeadersFooters {
				continue
			}
		case "Image", "Figure":
			if !opts.IncludeImages {
				continue
			}
			alt := chandraImageAlt(block.Node)
			if alt == "" {
				alt = strings.TrimSpace(textContent(block.Node))
			}
			if alt == "" {
				alt = label
			}
			if isChandraBlankImage(alt) {
				continue
			}
			imageIndex++
			imageID := fmt.Sprintf("chandra-page-%04d-image-%02d.jpg", pageNum, imageIndex)
			parts = append(parts, fmt.Sprintf("![%s](%s)", escapeMarkdownAlt(alt), imageID))
			if imgMeta := chandraExtractImageMetadata(pageImage, block, imageID, alt); imgMeta != nil {
				images = append(images, imgMeta)
			}
			continue
		}

		if label == "Section-Header" && blockText != "" && !strings.HasPrefix(strings.TrimSpace(blockText), "#") {
			blockText = "## " + strings.TrimSpace(stripMarkdownEmphasis(blockText))
		}
		blockText = cleanChandraTextArtifacts(blockText)
		if blockText != "" {
			parts = append(parts, blockText)
		}
	}

	return chandraParsedPage{
		Markdown: joinMarkdownBlocks(parts),
		Headers:  headers,
		Footers:  footers,
		Images:   images,
	}, nil
}

func parseChandraLayoutBlocks(raw string) ([]chandraLayoutBlock, error) {
	nodes, err := nethtml.ParseFragment(strings.NewReader(raw), nil)
	if err != nil {
		return nil, fmt.Errorf("failed to parse Chandra layout HTML: %w", err)
	}

	var blocks []chandraLayoutBlock
	for _, node := range nodes {
		collectChandraLayoutBlocks(node, &blocks)
	}
	return blocks, nil
}

func collectChandraLayoutBlocks(node *nethtml.Node, blocks *[]chandraLayoutBlock) {
	if node == nil {
		return
	}
	if node.Type == nethtml.ElementNode && node.Data == "div" {
		if label := attrValue(node, "data-label"); label != "" {
			*blocks = append(*blocks, chandraLayoutBlock{
				Label: label,
				BBox:  parseChandraBBox(attrValue(node, "data-bbox")),
				Node:  node,
			})
			return
		}
	}
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		collectChandraLayoutBlocks(child, blocks)
	}
}

func parseChandraBBox(raw string) [4]int {
	var bbox [4]int
	fields := strings.Fields(raw)
	if len(fields) != 4 {
		return bbox
	}
	for i, field := range fields {
		n, err := strconv.Atoi(field)
		if err != nil {
			return [4]int{}
		}
		bbox[i] = n
	}
	return bbox
}

func isChandraBlankImage(alt string) bool {
	normalized := strings.ToLower(strings.Join(strings.Fields(alt), " "))
	switch normalized {
	case "blank page", "blank white page", "blank image", "white page":
		return true
	default:
		return strings.Contains(normalized, "blank white page")
	}
}

func cleanChandraTextArtifacts(text string) string {
	normalized := strings.ToLower(strings.Join(strings.Fields(stripMarkdownEmphasis(text)), " "))
	if matched, _ := regexp.MatchString(`^picture at page \d+$`, normalized); matched {
		return ""
	}
	return text
}

func chandraImageAlt(node *nethtml.Node) string {
	var find func(*nethtml.Node) string
	find = func(n *nethtml.Node) string {
		if n == nil {
			return ""
		}
		if n.Type == nethtml.ElementNode && strings.ToLower(n.Data) == "img" {
			return strings.TrimSpace(attrValue(n, "alt"))
		}
		for child := n.FirstChild; child != nil; child = child.NextSibling {
			if alt := find(child); alt != "" {
				return alt
			}
		}
		return ""
	}
	return find(node)
}

func chandraExtractImageMetadata(pageImage image.Image, block chandraLayoutBlock, imageID, alt string) map[string]any {
	if pageImage == nil {
		return nil
	}
	sub, ok := pageImage.(interface {
		SubImage(r image.Rectangle) image.Image
	})
	if !ok {
		return nil
	}
	bounds := pageImage.Bounds()
	rect := normalizedBBoxToImageRect(block.BBox, bounds)
	if rect.Empty() {
		return nil
	}
	crop := sub.SubImage(rect)
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, crop, &jpeg.Options{Quality: 90}); err != nil {
		return nil
	}
	return map[string]any{
		"id":             imageID,
		"top_left_x":     rect.Min.X,
		"top_left_y":     rect.Min.Y,
		"bottom_right_x": rect.Max.X,
		"bottom_right_y": rect.Max.Y,
		"alt":            alt,
		"has_base64":     true,
		"image_base64":   "data:image/jpeg;base64," + base64.StdEncoding.EncodeToString(buf.Bytes()),
	}
}

func normalizedBBoxToImageRect(bbox [4]int, bounds image.Rectangle) image.Rectangle {
	width := bounds.Dx()
	height := bounds.Dy()
	x0 := bounds.Min.X + bbox[0]*width/defaultChandraBboxScale
	y0 := bounds.Min.Y + bbox[1]*height/defaultChandraBboxScale
	x1 := bounds.Min.X + bbox[2]*width/defaultChandraBboxScale
	y1 := bounds.Min.Y + bbox[3]*height/defaultChandraBboxScale
	rect := image.Rect(x0, y0, x1, y1).Intersect(bounds)
	if rect.Dx() <= 0 || rect.Dy() <= 0 {
		return image.Rectangle{}
	}
	return rect
}

func attrValue(node *nethtml.Node, key string) string {
	for _, attr := range node.Attr {
		if strings.EqualFold(attr.Key, key) {
			return attr.Val
		}
	}
	return ""
}

func textContent(node *nethtml.Node) string {
	if node == nil {
		return ""
	}
	if node.Type == nethtml.TextNode {
		return stdhtml.UnescapeString(node.Data)
	}
	var parts []string
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		parts = append(parts, textContent(child))
	}
	return strings.Join(strings.Fields(strings.Join(parts, " ")), " ")
}
