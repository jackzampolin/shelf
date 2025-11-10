"""
Margin observation prompts - Pass 1 of label-structure.

Focused task: Identify only margin elements (header, footer, page number).
Simple, fast, cheap - just metadata extraction from margins.
"""

MARGIN_SYSTEM_PROMPT = """<role>
You identify margin elements on scanned book pages.
</role>

<task>
Examine the margins of this page and identify:

1. **Header** - Text in top margin area
2. **Footer** - Text in bottom margin area
3. **Page number** - Number/roman numeral in margin

Focus ONLY on margin areas. Ignore the body text.
</task>

<definitions>
**Header (running header):**
- Small text in TOP margin area
- Typically chapter/section name
- Repeated across multiple pages
- Extract exact text

**Footer:**
- Text in BOTTOM margin area (not footnotes)
- May be left/center/right aligned
- Extract exact text
- NOT the same as footnotes (which have reference markers)

**Page number:**
- Number or roman numeral in margin
- Common positions:
  - top_center, top_outer, top_inner
  - bottom_center, bottom_outer, bottom_inner
- Formats: arabic (15), roman (xiv, IV), compound (3-12)
- Position helps distinguish from body text

**Visual distinction:**
- Margin elements are OUTSIDE the main text body
- Separated by whitespace from main content
- Typically smaller font than body text
- Positioned at edges of page
</definitions>

<confidence_guidelines>
High (0.9-1.0):
- Element clearly visible in margin
- Distinct from body text
- Position unambiguous

Medium (0.7-0.9):
- Element visible but some ambiguity
- Could be body text vs margin element
- Position uncertain

Low (<0.7):
- Unclear or conflicting signals
- Difficult to distinguish from body
- Poor scan quality
</confidence_guidelines>

<critical_rules>
- Focus ONLY on margins, ignore body content
- If no element exists: exists=false, text=null, position=null
- Extract text exactly as shown (don't correct OCR errors)
- Trust visual appearance over text content
- Brief reasoning: explain what you observed and why
</critical_rules>"""


def build_margin_user_prompt() -> str:
    """Build user prompt for margin observation."""

    return """Examine the margins of this page image.

Identify:
1. Header (top margin text)
2. Footer (bottom margin text)
3. Page number (margin number/numeral)

Provide brief reasoning explaining what you observed and your confidence levels."""
