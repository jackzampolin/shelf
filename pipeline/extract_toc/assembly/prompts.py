"""Prompts for Assembly: Lightweight ToC Assembly"""

SYSTEM_PROMPT = """You are a Table of Contents assembly specialist.

Your task is to merge ToC entries from multiple pages into a final, complete ToC structure.

Phase 1 has already extracted individual ToC entries from each page. Your job is simple:
1. Merge continuation entries (entries that span multiple pages)
2. Validate the sequence makes sense
3. Count chapters and sections
4. Assemble the final ToC

DO NOT re-interpret hierarchy or structure—trust Phase 1's extraction."""


def build_user_prompt(entries_by_page: dict, toc_range) -> str:
    """
    Build user prompt for lightweight assembly.

    Args:
        entries_by_page: Dict mapping page_num -> entries data
        toc_range: PageRange object

    Returns:
        Formatted prompt string
    """

    prompt = f"""<task>
Assemble the final Table of Contents from entries extracted across {len(entries_by_page)} pages (pages {toc_range.start_page}-{toc_range.end_page}).

Your job is SIMPLE:
1. **Merge continuations** - If an entry continues across pages, merge it
2. **Validate sequence** - Check that entries make sense in order
3. **Count entries** - Total chapters (Level 1) and sections (Level 2+3)
4. **Assemble final ToC** - Create the complete, ordered list

DO NOT re-interpret hierarchy or indentation. Phase 1 already determined hierarchy levels—trust those assignments.
</task>

<extracted_entries>
"""

    total_entries = 0
    for page_num in sorted(entries_by_page.keys()):
        page_data = entries_by_page[page_num]
        entries = page_data.get("entries", [])
        page_notes = page_data.get("notes", "")

        prompt += f"\n## Page {page_num}\n"
        if page_notes:
            prompt += f"Notes: {page_notes}\n"

        for entry in entries:
            entry_num = entry.get("entry_number")
            title = entry.get("title", "")
            level = entry.get("level", 1)
            level_name = entry.get("level_name")
            page_ref = entry.get("printed_page_number", "N/A")

            num_str = f"#{entry_num}" if entry_num else "---"
            type_str = f"[{level_name}]" if level_name else ""
            prompt += f"  [L{level}] {num_str} {type_str}: \"{title}\" → {page_ref}\n"
            total_entries += 1

    prompt += f"""
</extracted_entries>

Total extracted entries: {total_entries}

<assembly_instructions>

**CONTINUATION HANDLING**:
If an entry's metadata indicates `continues_to_next: true` or `continuation_from_previous: true`, check if the next page has a related entry that should be merged.

Example:
```
Page 5: "Chapter 1: An Incredibly Long Title That" (continues_to_next=true)
Page 6: "Continues on This Line" (continuation_from_previous=true)
```
Merge into: "Chapter 1: An Incredibly Long Title That Continues on This Line"

**VALIDATION CHECKS**:
1. Are entries in a logical order?
2. Are there obvious gaps or duplicates?
3. Do page numbers generally ascend (with allowances for roman numerals)?
4. Does the hierarchy structure make sense (no Level 3 without a Level 2 parent)?

**COUNTING BY LEVEL**:
- Count entries at each hierarchy level separately
- entries_by_level = {"1": <count of level 1>, "2": <count of level 2>, "3": <count of level 3>}
- Only include levels that actually have entries
- Example: If ToC only has Level 1 and 2, result is {"1": 15, "2": 42}

**TRUST PHASE 1**:
DO NOT change hierarchy levels. If Phase 1 said an entry is Level 2, keep it Level 2.
DO NOT re-capitalize or reformat titles beyond merging continuations.
DO NOT infer missing page numbers—preserve exactly as extracted.

</assembly_instructions>

<output_requirements>
Return JSON matching this schema (structured output enforced):

{
    "toc": {
        "entries": [
            {
                "entry_number": "5" or "II" or null,
                "title": "Introduction",
                "level": 1,
                "level_name": "chapter" or null,
                "printed_page_number": "1" or null
            }
        ],
        "toc_page_range": {
            "start_page": {toc_range.start_page},
            "end_page": {toc_range.end_page}
        },
        "entries_by_level": {
            "1": 15,
            "2": 42,
            "3": 8
        },
        "parsing_confidence": 0.95,
        "notes": ["Any assembly notes"]
    },
    "validation": {
        "issues_found": ["minor page number gap at entry 15"],
        "continuations_resolved": 3,
        "confidence": 0.95
    },
    "notes": "Overall assessment of assembly quality"
}

CRITICAL REQUIREMENTS:
- "level" MUST match what Phase 1 extracted (1, 2, or 3)
- "entry_number" is string or null
- "level_name" is string or null
- "toc_page_range" MUST be provided with start_page={toc_range.start_page}, end_page={toc_range.end_page}
- "entries_by_level" is object with string keys: {{"1": count, "2": count, "3": count}}
- Only include levels in entries_by_level that actually exist
- "parsing_confidence" should reflect overall confidence in the assembled ToC
- "continuations_resolved" = number of entries merged across pages
- Entries MUST be in the order they appear across pages (Page 1 entries, then Page 2, etc.)

</output_requirements>

Begin assembly."""

    return prompt
