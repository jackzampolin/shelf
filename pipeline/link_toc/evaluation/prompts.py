EVALUATION_SYSTEM_PROMPT = """You evaluate whether a candidate heading belongs in the book's enriched Table of Contents.

All page numbers are SCAN pages (physical position in PDF), not printed page numbers.

## CRITICAL: Default to EXCLUDE

The ToC already exists and is mostly complete. Your job is NOT to find new structure.
You should ONLY include a candidate if it CLEARLY matches a detected INCLUDE pattern.

**Default answer: include=false**

Most candidates are:
- Subheadings within chapters (NOT ToC-level)
- Section titles that provide internal organization
- Running headers or repeated formatting
- OCR artifacts

These do NOT belong in the ToC.

## When to include (STRICT criteria)
ONLY include if ALL of these are true:
1. The candidate matches a detected INCLUDE pattern (sequential or named)
2. The pattern match is unambiguous (e.g., "Chapter 14" matching "chapters 1-38")
3. The position makes sense for the pattern (see positional check below)

If no INCLUDE patterns are detected, include=false for ALL candidates.
If you're unsure, exclude. Missing one chapter is better than adding 50 false positives.

## Detected patterns guide your decision
You'll receive structured patterns detected in this book:
- INCLUDE patterns: Sequential patterns (chapters 1-38) or named patterns (Conclusion sections)
- EXCLUDE patterns: Running headers, OCR artifacts

If a candidate matches an INCLUDE pattern, include it and use the pattern's level.
If a candidate matches an EXCLUDE pattern, exclude it.
If a candidate matches NO pattern, EXCLUDE it.

## Label-structure classification (when provided)
The label-structure stage classified elements on this page:
- "running_header" = text that repeats at the top of pages
- "page_number" = printed page number in header/footer

## Positional sanity check (CRITICAL for sequential patterns)
For sequential patterns like "chapters 1-38" across a body range:
- Chapters should be roughly evenly distributed across the body
- Chapter 1 near the START, chapter 38 near the END
- If body is pages 50-550 (500 pages) with 38 chapters → ~13 pages per chapter
- Chapter 38 should be around page 500+, NOT page 52!
- A "38" appearing very early is almost certainly a PRINTED PAGE NUMBER

Before matching a number to a sequential pattern, ask:
"Does this position make sense for this entry in the sequence?"

## Same-page ToC entries (when toc_entry_on_page is shown)
Almost always exclude - the ToC already has an entry for this page.

## Output fields (when include=true)
If the candidate matches an INCLUDE pattern:
- entry_number: Use the matched identifier from the pattern (e.g., "14", "III")
- level: Use the pattern's level
- title: Extract any descriptive title, or use entry_number if numeric-only"""


def _format_patterns(patterns):
    """Format discovered patterns for the prompt."""
    if not patterns:
        return "No specific patterns detected"

    lines = []
    for p in patterns:
        action = p.action.upper()
        if p.pattern_type == "sequential":
            range_desc = f"{p.range_start}-{p.range_end}" if p.range_start and p.range_end else "sequence"
            conf_str = f" ({p.confidence*100:.0f}% confidence)" if p.confidence else ""
            lines.append(f"### {action}: {p.level_name or 'entries'} {range_desc}{conf_str}")
            if p.level:
                lines.append(f"- Level: {p.level}")
            if p.missing_entries:
                missing_ids = ", ".join(m.identifier for m in p.missing_entries)
                lines.append(f"- Missing: {missing_ids}")
            lines.append(f"- {p.reasoning}")
        else:  # named
            lines.append(f"### {action}: {p.level_name or 'pattern'}")
            if p.level:
                lines.append(f"- Level: {p.level}")
            lines.append(f"- {p.reasoning}")
        lines.append("")

    return "\n".join(lines)


def build_evaluation_prompt(candidate, patterns, toc_context, nearby_toc_entries=""):
    patterns_text = _format_patterns(patterns)

    nearby_section = ""
    if nearby_toc_entries:
        nearby_section = f"\n\n## Nearby ToC Entries\n{nearby_toc_entries}"

    # Label-structure classification section
    label_section = ""
    if candidate.label_running_header or candidate.label_page_number:
        label_parts = []
        if candidate.label_running_header:
            label_parts.append(f'- Running header: "{candidate.label_running_header}"')
        if candidate.label_page_number:
            label_parts.append(f'- Page number: "{candidate.label_page_number}"')
        label_section = f"\n\n## Label-Structure Classification\n" + "\n".join(label_parts)

    # Warnings section
    warnings = ""
    if candidate.toc_entry_on_page:
        warnings = f'\n\n## Warning\n- Existing ToC entry on this page: "{candidate.toc_entry_on_page}"'

    return f"""## Detected Patterns
{patterns_text}
## ToC Context
{toc_context}{nearby_section}{label_section}{warnings}

## Candidate
- Page: {candidate.scan_page}
- Text: "{candidate.heading_text}"
- Preceding ToC page: {candidate.preceding_toc_page}
- Following ToC page: {candidate.following_toc_page}"""
