"""Prompts for Phase 4: Validation and Assembly"""

SYSTEM_PROMPT = """You are a Table of Contents validator and assembler.

Your task is to review the identified elements from all ToC pages and:
1. Validate consistency across pages
2. Resolve continuations
3. Build the final hierarchical ToC structure
4. Confirm accuracy"""


def build_user_prompt(elements_by_page: dict, toc_range) -> str:
    """
    Build user prompt for validation and assembly.

    Args:
        elements_by_page: Dict mapping page_num -> elements data
        toc_range: PageRange object

    Returns:
        Formatted prompt string
    """

    prompt = f"""<task>
Review and validate the Table of Contents elements identified across {len(elements_by_page)} pages (pages {toc_range.start_page}-{toc_range.end_page}).

Your job is to:
1. **Validate consistency** - Check that elements make sense structurally
2. **Resolve continuations** - Merge elements that span multiple pages
3. **Build hierarchy** - Construct parent-child relationships from indentation
4. **Assemble final ToC** - Create the complete table of contents
</task>

<elements_data>
"""

    for page_num in sorted(elements_by_page.keys()):
        page_data = elements_by_page[page_num]
        elements = page_data.get("elements", [])
        page_notes = page_data.get("notes", "")

        prompt += f"\n## Page {page_num}\n"
        if page_notes:
            prompt += f"Notes: {page_notes}\n"
        prompt += f"Elements ({len(elements)}):\n"

        for idx, elem in enumerate(elements):
            prompt += f"  [{idx}] {elem.get('type', 'unknown')}: \"{elem.get('text', '')}\" (indent={elem.get('indentation_level', 0)}, page={elem.get('page_number', 'N/A')})\n"

    prompt += """
</elements_data>

<validation_checks>
1. **Structural consistency**:
   - Do indentation levels make sense?
   - Are page numbers in ascending order (generally)?
   - Are there missing or duplicate entries?

2. **Continuation handling**:
   - Which entries span multiple lines or pages?
   - Can they be merged into single ToC entries?

3. **Hierarchy construction**:
   - What is the parent-child structure?
   - Which elements are chapters vs sections vs entries?

4. **Completeness**:
   - Does this ToC make sense for a book?
   - Are there any obvious errors or omissions?
</validation_checks>

<output_requirements>
Return JSON matching this schema (structured output enforced):

{
    "toc": {
        "entries": [
            {
                "chapter_number": 1 or null,
                "title": "Chapter 1: Introduction",
                "printed_page_number": "1" or null,
                "level": 1 (MUST be 1, 2, or 3)
            }
        ],
        "toc_page_range": {
            "start_page": 6,
            "end_page": 7
        },
        "total_chapters": 15,
        "total_sections": 42,
        "parsing_confidence": 0.95,
        "notes": ["Any parsing notes"]
    },
    "validation": {
        "issues_found": ["minor page number gap"],
        "continuations_resolved": 3,
        "confidence": 0.95
    },
    "notes": "Overall assessment"
}

CRITICAL REQUIREMENTS:
- "level" MUST be 1, 2, or 3 (NOT 0!)
- "toc_page_range" MUST be provided
- "total_chapters" and "total_sections" MUST be provided
- All "required" fields must be present
</output_requirements>

Begin validation and assembly."""

    return prompt
