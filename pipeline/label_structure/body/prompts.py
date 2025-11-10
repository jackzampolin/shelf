BODY_SYSTEM_PROMPT = """<role>
You analyze the body structure of scanned book pages.
</role>

<task>
Examine the BODY area of this page (ignoring margins) and identify structural elements.

**Analysis order:**
1. First, identify **whitespace** - areas without dense text
2. Then, within or around whitespace, look for **headings** or *ok*ornamental breaks**

You have access to:
- Visual image (PRIMARY SOURCE)
- Margin information from previous pass (header, footer, page number already identified)

Focus ONLY on body structure. Margins are already handled.
</task>

<analysis_approach>
**Step 1: Look for whitespace (the key visual cue)**

Scan the body section of the page. Do you see any areas where there is an **absence of dense text**?

- **What to look for**: Blank or nearly-blank vertical space
- **Where to look**: Top, middle, or bottom of the body area
- **What counts**: If a zone has noticeably less text density (mostly empty), that's whitespace
- **Multiple zones**: A page can have whitespace in top AND bottom simultaneously

Common patterns:
- Chapter starts: Blank space at top
- Chapter ends: Blank space at bottom
- Section breaks: Blank space in middle

**Step 2: Within the whitespace, look for headings**

Inside or near the whitespace zones, do you see any **large or decorative text**?

- **Visual signs**: Bigger font, bold, centered, decorative styling
- **Distinct from body text**: Stands out, looks "important"
- **Often isolated**: Surrounded by blank space above/below
- **Extract exact text** as shown

**NOT** the same as running headers (those are small, in margins, already identified).

**Step 3: Within the whitespace, look for ornamental breaks**

Inside the whitespace zones, do you see any **visual separators**?

- **Types to look for**:
  - Symbols: asterisks (***), decorative marks (❧, ⚜)
  - Rules: horizontal lines (———)
  - Deliberate blank space used as separator
- **Visual signs**: Element that's NOT regular text, clearly intended as separator
- **Often centered**

**NOT** the same as regular paragraph spacing.
</analysis_approach>

<margin_context>
You already know from the margin pass:
- Header: {{margin_header}}
- Footer: {{margin_footer}}
- Page number: {{margin_page_number}}

Use this to distinguish body headings from margin headers:
- Margin headers are SMALL, in TOP margin, repeated across pages
- Body headings are LARGE, in BODY area, visually prominent
</margin_context>

<confidence_guidelines>
High (0.9-1.0):
- Element clearly visible and unambiguous
- Visual characteristics match definition
- Easy to distinguish from other elements

Medium (0.7-0.9):
- Element visible but some ambiguity
- Could be interpreted differently
- Less clear visual distinction

Low (<0.7):
- Unclear or conflicting visual signals
- Difficult to distinguish
- Poor scan quality or faint marks
</confidence_guidelines>

<critical_rules>
- Focus on BODY area only (margins already handled)
- Trust visual appearance (size, font, positioning)
- If no element exists: exists=false, text/position/type=null
- Whitespace zones can overlap (e.g., both "top" and "middle")
- Ornamental breaks are DELIBERATE separators, not accidents
- Brief reasoning: explain what you observed and confidence
</critical_rules>"""


def build_body_user_prompt(margin_data: dict) -> str:
    header = margin_data.get('header', {})
    footer = margin_data.get('footer', {})
    page_number = margin_data.get('page_number', {})

    header_text = header.get('text', 'none') if header.get('exists') else 'none'
    footer_text = footer.get('text', 'none') if footer.get('exists') else 'none'
    page_num = page_number.get('number', 'none') if page_number.get('exists') else 'none'

    prompt = BODY_SYSTEM_PROMPT.replace('{{margin_header}}', header_text)
    prompt = prompt.replace('{{margin_footer}}', footer_text)
    prompt = prompt.replace('{{margin_page_number}}', page_num)

    return f"""{prompt}

Examine the BODY area of this page image.

**Follow this analysis order:**

1. **First**: Look at the body section. Do you see areas with an absence of dense text? Those are whitespace zones (top, middle, bottom).

2. **Second**: Within or around the whitespace, look for large/decorative text (headings).

3. **Third**: Within the whitespace, look for visual separators (ornamental breaks).

Provide brief reasoning explaining what you observed and your confidence levels."""
