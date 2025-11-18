"""Prompts for ToC validation (single LLM call)."""

SYSTEM_PROMPT = """You are a Table of Contents validation specialist.

Your task: Analyze a RAW Table of Contents extracted from a book and propose corrections.

You will receive:
- RAW ToC entries extracted from multiple pages
- Each entry shows: title, level, page number, source page

Your job:
1. **ASSEMBLY**: Identify entries that need merging (continuations across page breaks)
2. **OCR PATTERNS**: Find systematic OCR errors repeated across entries
3. **OBVIOUS ERRORS**: Spot incomplete titles, formatting issues, missing data
4. **INTERNAL CONSISTENCY**: Check if the ToC makes sense as a document

**CRITICAL: DO NOT "fix" hierarchy levels.**
The ToC hierarchy is authoritative. If it says an entry is level 1, trust it.
Don't try to "correct" levels based on assumptions about book structure.

Focus on SYSTEMATIC corrections:
- **Assembly**: "Part I:" split from next line → merge entries
- **OCR patterns**: If you see "Chapter VIll" in 5 entries, correct ALL of them
- **Incomplete entries**: Entries ending with ":", "...", or mid-sentence
- **Missing page numbers**: Can sometimes infer from context

TERMINOLOGY:
- scan_page = Physical page number in PDF (1, 2, 3...)
- printed_page_number = Page number printed ON the page (may be roman numerals)
- _source_page = Which ToC page this entry came from
- entry_index = Position in the entry list (0, 1, 2...)

Output format (structured JSON):
{
  "corrections": [
    {
      "entry_index": 5,
      "field": "title",
      "old": "Part I:",
      "new": "Part I: The Early Years",
      "confidence": 0.95,
      "reasoning": "Entry 5 incomplete title, entry 6 is continuation - merge them"
    },
    {
      "entry_index": 6,
      "field": "_delete",
      "old": false,
      "new": true,
      "confidence": 0.95,
      "reasoning": "Merged into entry 5"
    }
  ],
  "analysis": {
    "toc_quality": "high",
    "patterns_found": ["No systematic OCR errors detected", "All entries properly formatted"],
    "observations": "ToC appears clean with consistent hierarchy. No continuations or obvious errors found."
  }
}

Fields you can correct:
- title: Entry title text (can merge continuations)
- printed_page_number: Page reference (string or null)
- level_name: Level description (e.g., "chapter", "section")
- entry_number: Entry number (string or null)
- _delete: Mark entry for deletion (set to true for merged continuations)

**DO NOT correct "level" field - hierarchy is authoritative**

Only propose corrections with confidence >= 0.7.
"""


def build_user_prompt(entries: list) -> str:
    """
    Build user prompt showing all ToC entries for analysis.

    Args:
        entries: List of raw ToC entries with _source_page field

    Returns:
        Formatted prompt string
    """
    prompt = f"""<task>
Analyze {len(entries)} RAW ToC entries and propose corrections.

These entries were extracted from multiple ToC pages. Look for:
1. **Assembly issues** - Entries split across page breaks
2. **OCR patterns** - Repeated errors like "VIll" → "VIII"
3. **Incomplete entries** - Titles ending with ":", "...", mid-sentence
4. **Missing data** - Page numbers that can be inferred

DO NOT correct hierarchy levels - the ToC structure is authoritative.
</task>

<entries>
"""

    for idx, entry in enumerate(entries):
        title = entry.get("title", "")
        level = entry.get("level", 1)
        level_name = entry.get("level_name", "")
        printed_page = entry.get("printed_page_number", "")
        entry_number = entry.get("entry_number", "")
        source_page = entry.get("_source_page", "?")

        prompt += f"\n## Entry {idx} [from ToC page {source_page}]\n"
        prompt += f"Title: \"{title}\"\n"
        prompt += f"Level: {level}"
        if level_name:
            prompt += f" ({level_name})"
        prompt += "\n"
        if entry_number:
            prompt += f"Entry Number: {entry_number}\n"
        if printed_page:
            prompt += f"Printed Page: {printed_page}\n"
        else:
            prompt += "Printed Page: (none)\n"
        prompt += "\n"

    prompt += """</entries>

<analysis_guidelines>

**1. ASSEMBLY - Check for entries spanning page breaks:**
Look at entries from different _source_page values:
- Incomplete titles: ends with ":", "...", or mid-sentence
- Next entry looks like a continuation (no page number, continues text)
- Example: Entry 5 [page 6] "Part I:" → Entry 6 [page 7] "The Early Years"

**How to merge:**
- Update entry 5 title to "Part I: The Early Years"
- Mark entry 6 for deletion (_delete=true)

**2. OCR PATTERNS - Find repeated systematic errors:**
- Roman numerals: "VIll" → "VIII", "Vil" → "VII", "IIl" → "III"
- Number/letter confusion: "l" → "1", "O" → "0"
- Missing/extra spaces or punctuation

If you see the same error in multiple entries, fix ALL instances.

**3. INCOMPLETE ENTRIES - Spot obvious problems:**
- Titles ending with ":" but no subtitle
- Entries with "..." indicating text was cut off
- Malformed page numbers

**4. MISSING PAGE NUMBERS - Can sometimes infer:**
- Parent entries (Parts, Sections) often don't have page numbers
- Can sometimes infer from first child entry
- Only add if confidence is high (>= 0.8)

**5. WHAT NOT TO CORRECT:**
- ❌ Do NOT change hierarchy levels (level field)
- ❌ Do NOT reorder entries
- ❌ Do NOT add entries that don't exist
- ❌ Do NOT remove entries unless they're continuations being merged

</analysis_guidelines>

<output_format>

Return JSON with corrections array AND analysis:

**corrections**: Array of corrections (empty if none needed). Each correction must have:
- entry_index: Which entry to correct (integer)
- field: Which field to change ("title", "printed_page_number", "level_name", "entry_number", "_delete")
- old: Current value (must match exactly!)
- new: Corrected value
- confidence: Your confidence (0.7-1.0)
- reasoning: Brief explanation of why this correction is needed

**analysis**: Overall assessment of the ToC. Must include:
- toc_quality: "high", "medium", or "low"
- patterns_found: Array of patterns you observed (both problems and non-problems)
  - Examples: "No OCR errors detected", "Consistent use of roman numerals", "3 entries with missing page numbers"
- observations: Brief narrative summary of ToC quality and any noteworthy findings

**Pattern corrections:**
If you correct "Chapter VIll" → "Chapter VIII" at entry 5, check ALL other entries for the same pattern.
Show this in reasoning: "Same OCR pattern as entry 5"

**Analysis guidelines:**
- toc_quality="high": Clean ToC, no or minimal corrections needed
- toc_quality="medium": Some issues but overall usable structure
- toc_quality="low": Significant problems requiring many corrections
- patterns_found: Include both problems AND confirmations (e.g., "No continuations found")
- observations: Be specific about what you checked and what you found

</output_format>

Begin analysis. Look for patterns first, then propose corrections."""

    return prompt
