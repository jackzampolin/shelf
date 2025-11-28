UNIFIED_EXTRACTION_PROMPT = """<role>
Book page structure and annotation extractor.
</role>

<task>
Extract structural metadata (headers, footers, page numbers) and content annotations
(footnote markers, footnote content, cross-references) from a book page.
</task>

<input>
<blended_ocr>
{blended_text}
</blended_ocr>

<paddle_ocr>
{paddle_text}
</paddle_ocr>

<headings>
{headings_json}
</headings>

<pattern_hints>
{pattern_hints_json}
</pattern_hints>
</input>

<context>
**OCR Sources:**
- `blended_ocr`: High-quality synthesized markdown from vision model (primary source)
- `paddle_ocr`: Raw OCR that often captures headers/page numbers others miss

**Pattern Hints (from mechanical extraction):**
- `has_mistral_footnote_refs`: Detected [^N] footnote markers
- `has_mistral_endnote_refs`: Detected ${{}}^{{N}}$ endnote markers
- `has_repeated_symbols`: Multiple *, †, ‡ (footnote indicators)
- `has_olm_chart_tags`: Detected <></> chart/table tags
- `has_mistral_images`: Detected ![alt](img.jpeg) image references

**Headings:** Already extracted mechanically, exclude from annotation detection.
</context>

<instructions>
## OCR Quality Check

If OCR is corrupted (repetitive garbage, random characters, nonsensical):
- Set all `present` fields to false
- Set confidence to "low"
- Use empty strings/lists
- Skip extraction

## Part 1: Structural Metadata

**1. Headers (running headers in top margin)**
- First lines in Paddle that are MISSING from blended OCR = header
- Typically: book title, chapter name, section name
- If top text matches a heading from mechanical extraction, it's a chapter title, not a running header

**2. Footers (running footers in bottom margin)**
- Last lines in Paddle that are MISSING from blended OCR = footer
- Typically: book title, chapter name, author name
- NOT footnote content (check pattern hints for footnote indicators)

**3. Page Numbers**
- Look ONLY in header/footer text identified above
- Patterns: "Page 34", "- 34 -", "34", "xiv" (Roman numerals)
- Location: header, footer, or margin
- NOT body text references: "see page 42" are references, not page numbers

## Part 2: Content Annotations

**After identifying headers/footers above, exclude those regions from annotation detection.**

**1. Reference Markers in Body Text**

Look for markers in body text (NOT in headers/footers/headings):

Marker types:
- Numeric superscript: ¹, ², ³ or small raised numbers
- Symbols: *, †, ‡, §, ¶ (may be superscript)
- Bracketed: [1], [2] or (1), (2)
- LaTeX: ${{}}^{{1}}$, ${{}}^{{2}}$ (from blended OCR)

Output per marker:
- marker_text: "17"
- marker_type: "numeric" | "symbol" | "letter" | "bracketed"
- is_superscript: true/false
- context: "...surrounding text¹⁷ more text..."
- confidence: "high" | "medium" | "low"

**2. Footnote Content at Bottom**

Look for footnote content at BOTTOM of page:

Indicators:
- Horizontal rule or separator (———, ___, whitespace gap)
- Text starts with matching marker (1., *, †)

Footnote vs Footer:
- Footnotes: Numbered annotations with content
- Footers: Running text (book title, chapter name) - identified in Part 1

Output per footnote:
- marker: "17"
- content: "Full footnote text..."
- confidence: "high" | "medium" | "low"
- source_provider: "blend" (always use "blend" for blended OCR source)

**3. Cross-References**

Look for internal document references:
- "see Chapter 3"
- "cf. page 42"
- "as discussed in Section 2.1"
- "Figure 3.4 shows..."
- "refer to Table 5"

Output per reference:
- link_text: "see Chapter 3"
- target_description: "Chapter 3"
- target_type: "chapter" | "section" | "page" | "figure" | "table" | "other"
- confidence: "high" | "medium" | "low"

**4. Visual Layout Indicators**
- has_horizontal_rule: Lines like ———, ___, === separating body from footnotes
- has_small_text_at_bottom: Text below visual break/whitespace

## Classification

**Footnotes vs Endnotes:**
- Footnotes: Markers + matching content at bottom of THIS page
- Endnotes: Markers + NO content (points to notes section elsewhere)

If markers found with NO content:
- Record markers (likely endnotes/citations)
- Set `footnotes_present: false`

## Edge Cases

**Exclude from annotation detection:**
- Headings (provided in context)
- Headers/footers (identified in Part 1)
- Page numbers (identified in Part 1)
- Math notation (x², e⁻ˣ)
- Chemical formulas (H₂O, CO₂)

**Empty pages:** All `*_present` fields false

**Poor OCR:** Mark confidence "low", don't force detections
</instructions>

<output_requirements>
Return JSON following UnifiedExtractionOutput schema:

Structure fields:
- `header`: {{present, text, confidence, source_provider}}
- `footer`: {{present, text, confidence, source_provider}}
- `page_number`: {{present, number, location, confidence, source_provider}}

Annotation fields:
- `markers_present`: true/false
- `markers`: Array of ReferenceMarker
- `footnotes_present`: true/false
- `footnotes`: Array of FootnoteContent
- `cross_references_present`: true/false
- `cross_references`: Array of CrossReference
- `has_horizontal_rule`: true/false
- `has_small_text_at_bottom`: true/false
- `confidence`: "high" | "medium" | "low" (overall)

**Confidence levels:**
- high: Clear structure/annotations, good OCR
- medium: Some ambiguity, acceptable OCR
- low: Poor OCR, uncertain detections

**source_provider values:**
- For structure fields: "paddle" (headers/footers typically from paddle) or "blend"
- For footnotes: always "blend"
</output_requirements>"""
