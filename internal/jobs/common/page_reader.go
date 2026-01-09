package common

// PageData contains all cached page content data.
type PageData struct {
	BlendMarkdown   string
	Headings        []HeadingItem
	PageNumberLabel *string
	RunningHeader   *string
}

// PageWithHeading contains page info with heading data for chapter detection.
type PageWithHeading struct {
	PageNum         int
	Heading         HeadingItem
	PageNumberLabel *string
	IsTocPage       bool
}
