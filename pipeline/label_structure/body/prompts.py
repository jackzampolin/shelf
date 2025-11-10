BODY_SYSTEM_PROMPT = """<role>
You analyze the body structure of scanned book pages.
</role>

<task>
Examine the BODY area of this page (ignoring margins) and identify structural elements.

**Analysis order:**
1. First, identify **whitespace** - areas without dense text
2. Then, within or around whitespace, look for **headings** or **ornamental breaks**

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

**Step 2: Within the whitespace, look for headings**

Inside or near the whitespace zones, do you see any **large or decorative text**?

- **Visual signs**: Bigger font, bold, centered, decorative styling
- **Distinct from body text**: Stands out, looks "important"
- **Often isolated**: Surrounded by blank space above/below
- **Extract exact text** as shown

**NOT** the same as headers -> those are small, in margins, and already identified in previous pass

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

<margin_vs_body_distinction>
**Distinguishing body headings from margin headers:**

Headers in margins (already identified in previous pass):
- Small text at the very top edge of page
- At the margin, separated from body

Body headings (what you're looking for now):
- LARGE or decorative text in BODY area
- Visually prominent (stands out)
- Surrounded by whitespace
- Inside the body, not at the edge

If you see large, prominent text in the body area → heading
If it's small text at the edge → that was already identified
</margin_vs_body_distinction>

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
    """Build user prompt with optional margin context."""

    # Build margin context section only if elements exist
    margin_context_lines = []

    header = margin_data.get('header', {})
    if header.get('exists'):
        margin_context_lines.append(f"- Header found: \"{header.get('text')}\"")

    footer = margin_data.get('footer', {})
    if footer.get('exists'):
        margin_context_lines.append(f"- Footer found: \"{footer.get('text')}\"")

    page_number = margin_data.get('page_number', {})
    if page_number.get('exists'):
        margin_context_lines.append(f"- Page number found: {page_number.get('number')}")

    # Only include margin context if something was found
    margin_context = ""
    if margin_context_lines:
        margin_context = "\n**Context from margin pass:**\n" + "\n".join(margin_context_lines) + "\n\nThese margin elements are already identified. Focus only on the BODY area.\n"

    return f"""{BODY_SYSTEM_PROMPT}

Examine the BODY area of this page image.
{margin_context}
**Follow this analysis order:**

1. **First**: Look at the body section. Do you see areas with an absence of dense text? Those are whitespace zones (top, middle, bottom).

2. **Second**: Within or around the whitespace, look for large/decorative text (headings).

3. **Third**: Within the whitespace, look for visual separators (ornamental breaks).

Provide brief reasoning explaining what you observed and your confidence levels."""
