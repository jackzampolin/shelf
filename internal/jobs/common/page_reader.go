package common

// PageData contains all cached page content data.
type PageData struct {
	OcrMarkdown string
	Headings    []HeadingItem
}

// PageWithHeading contains page info with heading data for chapter detection.
type PageWithHeading struct {
	PageNum int
	Heading HeadingItem
}
