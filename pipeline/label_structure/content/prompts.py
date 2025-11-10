"""
Content flow prompts - Pass 3 of label-structure.

Focused task: Text continuation and footnotes (text-only analysis).
Uses OCR + margin + body context. No vision needed.
"""

CONTENT_SYSTEM_PROMPT = """<role>
You analyze text content flow in scanned book pages.
</role>

<task>
Analyze the OCR text to determine:

1. **Text continuation** - Does text flow across page boundaries?
2. **Footnotes** - Are there footnotes with reference markers?

You have access to:
- OCR text (PRIMARY SOURCE for this pass)
- Margin information (header, footer, page number)
- Body structure (heading, whitespace, ornamental breaks)

This is TEXT-ONLY analysis. Focus on content, not layout.
</task>

<definitions>
**Text continuation:**
- **from_previous**: Text continues FROM previous page
  - Starts mid-sentence (no capital letter)
  - Starts mid-paragraph (continues thought)
  - No clear beginning marker (no chapter start, no paragraph indent at top)

- **to_next**: Text continues TO next page
  - Ends mid-sentence (no period, ends with comma/conjunction)
  - Ends mid-paragraph (no concluding thought)
  - Text flows to bottom edge without natural ending

**Footnotes:**
- Small text at bottom of page
- Has reference markers: ¹, ², ³, *, †, ‡, §
- Often preceded by horizontal line or separator
- NOT the same as footer (footer is margin metadata)
- Look for marker patterns in text
</definitions>

<analysis_guidelines>
**Text continuation signals:**

From previous page (true):
- Starts with lowercase: "and then he said..."
- Mid-sentence start: "to the next location where..."
- Continues thought: no paragraph break at top

From previous page (false):
- Starts with capital: "The beginning of..."
- Clear paragraph start
- Chapter/section heading at top

To next page (true):
- Ends mid-sentence: "and he went to the"
- Ends with comma: "the results were interesting,"
- Ends with conjunction: "but"
- No period at end

To next page (false):
- Ends with period: "...and that was that."
- Natural conclusion
- Chapter/section ends

**Footnote markers:**
- Superscript numbers: text¹, passage²
- Asterisks: word*, phrase**
- Symbols: †, ‡, §
- Look at BOTTOM of OCR text for footnote content
- Multiple footnotes per page possible
</analysis_guidelines>

<context_usage>
Use margin and body context to inform analysis:

**Margin context:**
- Header: {{margin_header}}
- Footer: {{margin_footer}}
- Page number: {{margin_page_number}}

**Body context:**
- Heading exists: {{heading_exists}}
- Heading text: {{heading_text}}
- Whitespace zones: {{whitespace_zones}}

**How context helps:**
- If heading at top → likely page starts fresh (from_previous=false)
- If significant whitespace at bottom → likely natural ending (to_next=false)
- If footer exists → helps distinguish footer from footnotes
</context_usage>

<confidence_guidelines>
High (0.9-1.0):
- Clear sentence structure indicators
- Obvious markers (footnote symbols, mid-sentence breaks)
- Context confirms analysis

Medium (0.7-0.9):
- Some ambiguity in sentence boundaries
- Paragraph structure unclear
- Context partially helpful

Low (<0.7):
- Poor OCR quality
- Ambiguous text structure
- Conflicting signals
</confidence_guidelines>

<critical_rules>
- TEXT-ONLY analysis (no image access in this pass)
- Use margin/body context to inform decisions
- Footnotes have REFERENCE MARKERS (not just bottom text)
- Footer ≠ footnotes (footer is margin metadata)
- Brief reasoning: explain what you observed
</critical_rules>"""


def build_content_user_prompt(ocr_text: str, margin_data: dict, body_data: dict) -> str:
    """Build user prompt for content analysis with full context."""

    # Extract margin context
    header = margin_data.get('header', {})
    footer = margin_data.get('footer', {})
    page_number = margin_data.get('page_number', {})

    header_text = header.get('text', 'none') if header.get('exists') else 'none'
    footer_text = footer.get('text', 'none') if footer.get('exists') else 'none'
    page_num = page_number.get('number', 'none') if page_number.get('exists') else 'none'

    # Extract body context
    heading = body_data.get('heading', {})
    whitespace = body_data.get('whitespace', {})

    heading_exists = "yes" if heading.get('exists') else "no"
    heading_text = heading.get('text', 'none') if heading.get('exists') else 'none'
    whitespace_zones = str(whitespace.get('zones', []))

    # Inject context into prompt
    prompt = CONTENT_SYSTEM_PROMPT.replace('{{margin_header}}', header_text)
    prompt = prompt.replace('{{margin_footer}}', footer_text)
    prompt = prompt.replace('{{margin_page_number}}', page_num)
    prompt = prompt.replace('{{heading_exists}}', heading_exists)
    prompt = prompt.replace('{{heading_text}}', heading_text)
    prompt = prompt.replace('{{whitespace_zones}}', whitespace_zones)

    ocr_display = ocr_text if ocr_text else "(No OCR text available)"

    return f"""{prompt}

Analyze this OCR text:

{ocr_display}

Determine:
1. Text continuation (from previous, to next)
2. Footnotes (presence of reference markers)

Provide brief reasoning explaining your analysis."""
