STRUCTURAL_METADATA_PROMPT = """Extract structural metadata from three OCR outputs of the same book page.

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

<pattern_hints>
{pattern_hints_json}
</pattern_hints>

**Pattern Hints:**
- `has_mistral_footnote_refs`: Page has [^N] footnote markers
- `mistral_footnote_count`: Number of footnote markers detected
- `has_repeated_symbols`: Multiple instances of *, †, ‡ (footnote indicators)
- `has_mistral_images`: Page contains ![alt](img.jpeg) image references

**Important:** If pattern hints indicate footnotes, be careful not to confuse footnote content at bottom with running footers.

## OCR Quality Check

If ANY OCR output is corrupted (repetitive garbage like "I I I I...", random characters, clearly nonsensical):
- Set ALL observations to `present: false` with `confidence: "low"`
- Use empty strings for text fields
- Skip analysis - don't try to extract from garbage

## Structural Metadata Extraction

**1. Headers (running headers in top margin)**
- Compare Paddle vs Mistral/OLM
- First lines in Paddle MISSING from Mistral/OLM = header
- Typically: book title, chapter name, section name
- If top text matches a heading from Pass 1, it's likely a chapter title, not a running header
- If Paddle ≈ Mistral/OLM at top, no header

**2. Footers (running footers in bottom margin)**
- Compare Paddle vs Mistral/OLM
- Last lines in Paddle MISSING from Mistral/OLM = footer
- Typically: book title, chapter name, author name
- NOT footnote content (check pattern hints for footnote indicators)
- If Paddle ≈ Mistral/OLM at bottom, no footer

**3. Page Numbers**
- Look ONLY in header/footer text identified above
- Patterns: "Page 34", "- 34 -", "34", "xiv" (Roman numerals)
- Location: header, footer, or margin
- NOT body text references: "see page 42", "pages 15-20" are references, not page numbers
- Extract the number/numeral value

**Note:** This is ONLY for structural elements (headers/footers/page_num).
Do NOT confuse footnote content with running footers.

**Confidence:** high (clear) | medium (somewhat clear) | low (uncertain)"""
