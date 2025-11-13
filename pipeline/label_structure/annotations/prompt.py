ANNOTATIONS_EXTRACTION_PROMPT = """<role>
Content annotation extractor for book pages.
</role>

<task>
Extract citations, footnotes, endnotes, and cross-references from OCR text.
</task>

<input>
<mistral_ocr>
{mistral_text}
</mistral_ocr>

<olm_ocr>
{olm_text}
</olm_ocr>

<paddle_ocr>
{paddle_text}
</paddle_ocr>

<headings>
{headings_json}
</headings>

<structure>
{structure_json}
</structure>

<pattern_hints>
{pattern_hints_json}
</pattern_hints>
</input>

<context>
**Pattern Hints:**
- `has_mistral_footnote_refs`: Mistral detected [^N] footnote markers
- `has_mistral_endnote_refs`: Mistral detected ${{}}^{{N}}$ endnote markers
- `has_repeated_symbols`: Multiple *, †, ‡ (footnote indicators)
- `has_olm_chart_tags`: OLM detected <></> chart/table tags
- `has_mistral_images`: Mistral detected ![alt](img.jpeg) image references

**Structure (exclude from annotation detection):**
- Header text: Already extracted in structure stage
- Footer text: Already extracted in structure stage
- Page number: Already extracted in structure stage
- Headings: Already extracted mechanically

Do NOT detect markers in header/footer regions or headings.
</context>

<instructions>
## OCR Quality Check

If ANY OCR is corrupted (repetitive garbage, random characters, nonsensical):
- Set all `*_present` fields to false
- Set confidence to "low"
- Use empty lists
- Skip extraction

## Task 1: Reference Markers in Body Text

Look for markers in body text (NOT in headers/footers/headings from context):

**Marker Types:**
- Numeric superscript: ¹, ², ³ or small raised numbers
- Symbols: *, †, ‡, §, ¶ (may be superscript)
- Bracketed: [1], [2] or (1), (2)

**Detection:**
- Check all three OCRs (superscripts differ across providers)
- Mistral may preserve Unicode superscripts (¹²³)
- Paddle may show regular numbers
- OLM varies

**Output per marker:**
```json
{{
  "marker_text": "17",
  "marker_type": "numeric",
  "is_superscript": true,
  "context": "...surrounding text¹⁷ more text...",
  "confidence": "high"
}}
```

## Task 2: Footnote Content at Bottom

Look for footnote content at BOTTOM of page:

**Indicators:**
- Small text at bottom (Paddle may show font size)
- Horizontal rule or separator (———, ___, whitespace gap)
- Text starts with matching marker (1., *, †)

**Footnote vs Footer:**
- Footnotes: Numbered annotations with content
- Footers: Running text (book title, chapter name) - already in structure context

**Output per footnote:**
```json
{{
  "marker": "17",
  "content": "Full footnote text...",
  "confidence": "high",
  "source_provider": "mistral"
}}
```

**Match markers from body to content at bottom.**

## Task 3: Cross-References

Look for internal document references:

**Patterns:**
- "see Chapter 3"
- "cf. page 42"
- "as discussed in Section 2.1"
- "Figure 3.4 shows..."
- "refer to Table 5"

**Output per reference:**
```json
{{
  "link_text": "see Chapter 3",
  "target_description": "Chapter 3",
  "target_type": "chapter",
  "confidence": "high"
}}
```

**Target types:** chapter, section, page, figure, table, other

## Task 4: Visual Layout Indicators

**Horizontal Rule:**
- Lines: ———, ___, ===
- Separator between body and footnotes
- Set `has_horizontal_rule: true` if present

**Small Text at Bottom:**
- Paddle may indicate smaller font
- Text below visual break/whitespace
- Set `has_small_text_at_bottom: true` if detected

## Classification

**Footnotes vs Endnotes:**
- Footnotes: Markers + matching content at bottom of THIS page
- Endnotes: Markers + NO content (points to notes section elsewhere)

**If markers found with NO content:**
- Record markers (likely endnotes/citations)
- Set `footnotes_present: false`

## Edge Cases

**Exclude from detection:**
- Headings (in context)
- Headers/footers (in context)
- Page numbers (in context)
- Math notation (x², e⁻ˣ)
- Chemical formulas (H₂O, CO₂)

**Empty pages:**
- All `*_present` fields false

**Poor OCR:**
- Mark confidence "low"
- Don't force detections
</instructions>

<output_requirements>
Return JSON following AnnotationsOutput schema:
- `markers_present`: true/false
- `markers`: Array of ReferenceMarker
- `footnotes_present`: true/false
- `footnotes`: Array of FootnoteContent
- `cross_references_present`: true/false
- `cross_references`: Array of CrossReference
- `has_horizontal_rule`: true/false
- `has_small_text_at_bottom`: true/false
- `confidence`: "high" | "medium" | "low"

**Confidence levels:**
- high: Clear markers/footnotes, good OCR
- medium: Some ambiguity, acceptable OCR
- low: Poor OCR, uncertain detections
</output_requirements>"""
