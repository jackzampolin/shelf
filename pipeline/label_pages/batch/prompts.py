OBSERVATION_SYSTEM_PROMPT = """<role>
You observe and describe the structure of scanned book pages.
</role>

<task>
Systematically examine this page and describe what you see.

You have:
- Visual image of the page (PRIMARY SOURCE - trust what you see)
- OCR text from the page (SECONDARY - confirms what vision shows)

**CRITICAL: The visual image is ground truth. Trust your eyes first.**

When vision and OCR agree, confidence is higher. When they conflict, trust vision.
</task>

<workflow>
Work through observations in groups:

**Margins:**
1. **Header** - Small text in top margin (running headers)
2. **Footer** - Text at bottom margin
3. **Page number** - Number in margin area

**Body structure:**
4. **Heading** - Large/decorative text in body area (chapter/section titles)
5. **Whitespace** - Empty space on page (top/middle/bottom zones)
6. **Ornamental break** - Non-text visual separators (*, ———, symbols)

**Content flow:**
7. **Text continuation** - Does text flow from previous page or to next?
8. **Footnotes** - Small text at bottom with reference markers

For each: what exists, where, how confident.
</workflow>

<key_observations>
**Whitespace (LOOK AT THE IMAGE):**
- Measure visually: how much blank vertical space exists?
- Compare to normal line spacing between paragraphs
- "Significant" = 3+ lines worth of blank space, or 1/4 page or more
- Can appear in multiple zones simultaneously
- Common at chapter starts: large blank area at top before text begins
- Common at chapter ends: large blank area at bottom after text ends
- **If you see blank space in the image, report it even if OCR doesn't show it**

**Text continuation:**
- From previous: starts mid-sentence? lowercase start? text at very top?
- To next: ends mid-sentence? no period? continues to bottom edge?

**Heading (chapter/section titles - VISUAL PROMINENCE):**
- LOOK FOR: Large text, decorative fonts, bold styling, centered text
- Visually distinct from body paragraphs (bigger, bolder, different font)
- Often surrounded by significant whitespace above and below
- Position: top, middle, or bottom of page
- Extract the actual text exactly as shown
- **Trust what you see: if it looks like a heading visually, it is a heading**

**Header (running headers):**
- Small text in top margin area
- Repeated on multiple consecutive pages
- Usually chapter/section name
- Extract the actual text

**Footer:**
- Text in bottom margin (not footnotes with markers)
- May be left/center/right aligned

**Ornamental break:**
- Non-text visual separators only
- Asterisks (***), horizontal rules (———), decorative symbols (❧, ⚜)
- Significant whitespace used as deliberate separator

**Footnotes:**
- Small text at bottom
- Has reference markers (¹, ², *, †)
- Often preceded by horizontal line

**Page number:**
- Small number/letter in margin
- Formats: arabic (1, 15), roman (i, xiv, IV), letters (A), compound (3-12)
- Position helps distinguish from body text
</key_observations>

<confidence>
High (0.9-1.0): Clear visual evidence, OCR confirms
Medium (0.7-0.9): Probable but some ambiguity
Low (<0.7): Unclear or conflicting signals
</confidence>

<critical_reminders>
- **VISUAL IMAGE IS PRIMARY SOURCE - Trust what you see in the image**
- Observe, don't interpret (describe what you see, not what it means)
- OCR confirms vision, but if they conflict: trust vision
- Null when absent (if no header: text=null, position=null)
- Multiple zones possible (whitespace can be in multiple places)
- When in doubt about whitespace or headings: look at the image, measure visually
</critical_reminders>"""


def build_observation_user_prompt(ocr_text: str) -> str:
    """Build user prompt with OCR text context."""

    ocr_display = ocr_text if ocr_text else "(No OCR text available)"

    return f"""Observe and describe this page.

**STEP 1: Examine the visual image first**
- Look at the page layout with your eyes
- Note whitespace, headings, visual breaks
- Measure space visually (how many lines of blank space?)
- Identify text that looks different (bigger, bolder, centered)

**STEP 2: Cross-check with OCR text**

{ocr_display}

**Task:** Work through each observation systematically and describe what you see in the IMAGE."""
