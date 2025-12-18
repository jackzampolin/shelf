package label

// SystemPrompt is the system prompt for label structure extraction.
// Copied from Python: pipeline/label_structure/unified/prompt.py
const SystemPrompt = `You extract page numbers and running headers from book pages.

## Page Numbers

Location: Usually in header or footer region (first/last lines)
Formats: "34", "- 34 -", "Page 34", "xiv" (roman numerals for front matter)
NOT page numbers: "see page 42", "on page 10" (these are references in body text)

## Running Headers

Running headers repeat on consecutive pages within a chapter/section.
Common patterns:
- Chapter title on left pages, book title on right pages
- "Chapter 3: The Beginning" or just "The Beginning"
- Author name on one side, title on other
- Section names in academic texts

Running headers are NOT:
- Chapter headings (# Heading syntax) - these start new sections
- Footnote content at bottom of page
- Body text

Key insight: The same running header text appears on many consecutive pages.`

// UserPromptTemplate is the user prompt template for label extraction.
// Use fmt.Sprintf(UserPromptTemplate, blendedText)
const UserPromptTemplate = `Extract the page number and running header from this page:

%s`
