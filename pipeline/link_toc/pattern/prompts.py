PATTERN_SYSTEM_PROMPT = """You analyze candidate headings to identify structural patterns for the enriched ToC.

All page numbers are SCAN pages (physical position in the PDF), not printed page numbers.

You receive:
1. Table of Contents entries (already linked to scan pages)
2. Candidate headings found in the book body that are NOT in the ToC

Your job: Identify structural patterns and output them in a structured format.

## discovered_patterns

Each pattern represents a structural element type. Two pattern_types:

### sequential patterns (action: include)
Numbered sequences like chapters, parts, appendices:
- pattern_type: "sequential"
- level_name: "chapter", "part", "appendix", "section", etc.
- range_start/range_end: The sequence bounds (e.g., "1" to "38", "I" to "X")
- level: Structural depth (1=part, 2=chapter, 3=section)
- confidence: How complete is the pattern? (found entries / expected entries)
- missing_entries: Gaps in the sequence with predicted page ranges

Example: Candidates show "1", "2", "3", "5", "6" → sequential pattern 1-6 with "4" missing.

### named patterns (action: include or exclude)
Repeated structural names:
- pattern_type: "named"
- level_name: "conclusion", "introduction", "running_header", etc.
- level: For include patterns only
- action: "include" for real structure, "exclude" for noise

Example: Multiple "Conclusion" headings at chapter ends → named pattern to include.
Example: Running headers repeat chapter titles → named pattern to exclude.

## excluded_page_ranges (CRITICAL)
Page ranges to skip entirely. **Always exclude**:
- Notes section (from "Notes" ToC entry to next section)
- Bibliography section (from "Bibliography" ToC entry to next section)
- Index section (from "Index" ToC entry to end)
- Acknowledgments, Copyright pages

Look at the ToC entries to identify these sections and their page ranges.
Any candidate headings in these ranges will be automatically excluded from evaluation.

## requires_evaluation
Set false ONLY when ALL candidates are clearly noise. Default true.

## reasoning
Brief summary of your analysis."""


def build_pattern_prompt(toc_entries, candidate_headings, body_range):
    toc_lines = [f"  p{e.scan_page}: {e.entry_number + '. ' if e.entry_number else ''}{e.title}"
                 for e in toc_entries]

    candidate_lines = [f"  p{c.scan_page}: \"{c.heading_text}\""
                       for c in candidate_headings]

    return f"""## ToC Entries (linked)
{chr(10).join(toc_lines)}

## Candidate Headings (NOT in ToC, pages {body_range[0]}-{body_range[1]})
{chr(10).join(candidate_lines)}

Analyze patterns and output JSON."""
