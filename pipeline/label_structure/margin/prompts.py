MARGIN_SYSTEM_PROMPT = """<role>
You identify margin elements on scanned book pages.
</role>

<task>
Look at the TOP and BOTTOM margin areas of this page (not the main body text).

**Analysis order:**
1. First, scan the top margin - do you see any text?
2. Then, scan the bottom margin - do you see any text?
3. Finally, look for numbers in either margin area

Focus ONLY on margin areas. Ignore the body text.
</task>

<analysis_approach>
**Step 1: Look at the top margin area**

Do you see any **small text at the very top** of the page, above the main body text?

- **What to look for**: Text separated from body by whitespace, at top edge
- **Size**: Often smaller than body text, sometimes same size
- **If yes**: Extract the exact text

**Step 2: Look at the bottom margin area**

Do you see any **text at the very bottom** of the page, below the main body text?

- **What to look for**: Text separated from body by whitespace, at bottom edge
- **Position**: Can be left, center, or right aligned
- **NOT footnotes**: Footnotes have reference markers (¹, ², *), this is plain text
- **If yes**: Extract the exact text

**Step 3: Look for numbers in the margins**

Do you see a **number or roman numeral** in either margin area (top or bottom)?

- **What to look for**: Isolated number/numeral at edge of page
- **Positions**:
  - Top: center, outer edge, inner edge
  - Bottom: center, outer edge, inner edge
- **Formats**:
  - Arabic numerals: 15, 240
  - Roman numerals: xiv, IV, xlii
  - Compound: 3-12, A-5
- **Visual test**: Is it separated from body text? At the page edge?
- **If yes**: This is a page number - note the number and position
</analysis_approach>

<visual_distinction>
**How to tell margin elements from body text:**
- **Location**: At the very top or bottom edge of the page
- **Separation**: Whitespace gap between margin element and body text
- **Size**: Often (but not always) smaller font than body text
- **Positioning**: At edges, not in the main text flow
</visual_distinction>

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

    return """Examine the margin areas of this page image.

**Follow this analysis order:**

1. **First**: Look at the top margin. Do you see small text at the very top, above the main body? If yes, that's a header.

2. **Second**: Look at the bottom margin. Do you see text at the very bottom, below the main body? If yes , that's a footer (NOT footnotes with markers).

3. **Third**: Look for a number or roman numeral in either margin. If yes, that's the page number.

Provide brief reasoning explaining what you observed and your confidence levels."""
