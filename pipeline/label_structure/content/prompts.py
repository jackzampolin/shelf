"""
Content flow prompts - Pass 3 of label-structure.

Focused task: Text continuation and footnotes (text-only analysis).
Uses OCR + margin + body context. No vision needed.
"""

CONTENT_SYSTEM_PROMPT = """<role>
You analyze text content flow in scanned book pages.
</role>

<task>
Read the OCR text and answer two questions:

1. **Text continuation**: Does the text flow across page boundaries?
2. **Footnotes**: Are there footnotes with reference markers?

**Analysis order:**
1. First, look at how the text starts - does it continue from previous page?
2. Second, look at how the text ends - does it continue to next page?
3. Third, look at the bottom of the text - are there footnote markers?

You have access to:
- OCR text (PRIMARY SOURCE for this pass)
- Context from previous passes (margin + body observations)

This is TEXT-ONLY analysis. Focus on content, not layout.
</task>

<analysis_approach>
**Step 1: Does text continue FROM previous page?**

Look at the **first few words** of the OCR text. Does it start mid-sentence or mid-paragraph?

**Signs of continuation (from_previous=true):**
- Starts with lowercase: "and then he said..."
- Starts mid-sentence: "to the next location where..."
- No paragraph break at start (continues thought)

**Signs of fresh start (from_previous=false):**
- Starts with capital: "The beginning of..."
- Clear paragraph start (new thought)
- Heading text appears at start

**Step 2: Does text continue TO next page?**

Look at the **last few words** of the OCR text. Does it end mid-sentence or mid-paragraph?

**Signs of continuation (to_next=true):**
- Ends mid-sentence: "and he went to the"
- Ends with comma: "the results were interesting,"
- Ends with conjunction: "but", "and", "or"
- No period at end (incomplete thought)

**Signs of natural ending (to_next=false):**
- Ends with period: "...and that was that."
- Natural conclusion (complete thought)
- Large gap at bottom (from whitespace context)

**Step 3: Are there footnotes?**

Look at the **bottom portion** of the OCR text. Do you see reference markers?

**Footnote markers to look for:**
- Superscript numbers: text¹, passage²
- Asterisks: word*, phrase**
- Symbols: †, ‡, §
- Often preceded by horizontal line: ———

**What footnotes look like:**
- Reference marker in body text
- Corresponding text at bottom with same marker
- NOT the same as footer (footer has no markers)
- Multiple footnotes per page possible
</analysis_approach>

<using_context>
**Context from previous passes:**

You'll receive observations from margin and body analysis:
- What headers/footers/page numbers were found (if any)
- What headings were found in the body (if any)
- Where whitespace zones exist (if any)

Use this context to inform your text analysis, but base your conclusions on the OCR text itself.
</using_context>

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
    """Build user prompt for content analysis with optional context."""

    # Build context section only if elements exist
    context_lines = []

    # Margin context
    header = margin_data.get('header', {})
    if header.get('exists'):
        context_lines.append(f"- Header found: \"{header.get('text')}\"")

    footer = margin_data.get('footer', {})
    if footer.get('exists'):
        context_lines.append(f"- Footer found: \"{footer.get('text')}\"")

    page_number = margin_data.get('page_number', {})
    if page_number.get('exists'):
        context_lines.append(f"- Page number: {page_number.get('number')}")

    # Body context
    heading = body_data.get('heading', {})
    if heading.get('exists'):
        context_lines.append(f"- Heading found: \"{heading.get('text')}\"")

    whitespace = body_data.get('whitespace', {})
    zones = whitespace.get('zones', [])
    if zones:
        zones_str = ", ".join(zones)
        context_lines.append(f"- Whitespace zones: {zones_str}")

    # Only include context if something was found
    context_block = ""
    if context_lines:
        context_block = "\n**Context from previous passes:**\n" + "\n".join(context_lines) + "\n\n"

    ocr_display = ocr_text if ocr_text else "(No OCR text available)"

    return f"""{CONTENT_SYSTEM_PROMPT}

Analyze this OCR text:

{ocr_display}
{context_block}
**Determine:**
1. Text continuation (from previous, to next)
2. Footnotes (presence of reference markers)

Provide brief reasoning explaining your analysis."""
