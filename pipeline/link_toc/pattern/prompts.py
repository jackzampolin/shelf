PATTERN_SYSTEM_PROMPT = """You analyze a book's structure to identify patterns of entries NOT in the Table of Contents.

All page numbers are SCAN pages (physical position in the PDF), not printed page numbers.

You receive:
1. Table of Contents entries (already linked to scan pages)
2. Candidate headings detected in the book body that are NOT in the ToC

Your job: Identify sequential patterns (like chapters 1-38) that should be discovered.

## CRITICAL: Check ToC First - Avoid Duplicate Discovery

Before outputting ANY sequential pattern, check if the ToC already covers it:
- If ToC has entries with entry_number "1", "2", "3"... those chapters are ALREADY in ToC
- If ToC has [chapter] entries numbered 1-83 → do NOT output a chapter 1-83 pattern
- Only output patterns for structural elements MISSING from the ToC

Example - DO NOT output pattern:
  ToC shows: p14: [chapter] 1. Ellis Island, p17: [chapter] 2. A Benefactor, ... p490: [chapter] 83. Final
  → Chapters 1-83 are ALREADY LINKED. Output discovered_patterns: [] (empty)

Example - DO output pattern:
  ToC shows: p10: [part] I. Early Years, p100: [part] II. War Years, p200: [part] III. Legacy
  Candidates show: "CHAPTER 1" at p15, "CHAPTER 2" at p30, "CHAPTER 5" at p60
  → Parts are in ToC but chapters are NOT. Output chapter pattern 1-N.

The goal is to DISCOVER missing structure, not re-discover what's already in the ToC.

## discovered_patterns

Each pattern represents a structural element type that should be searched for.

### sequential patterns
Numbered sequences like chapters, parts, appendices:
- pattern_type: "sequential"
- level_name: "chapter", "part", "appendix", "section", etc.
- range_start/range_end: The FULL sequence bounds (e.g., "1" to "38")
- level: Structural depth (1=part, 2=chapter, 3=section)
- heading_format: The ACTUAL format of headings in the candidate_headings, using {n} as placeholder:
  - If candidate headings show "1", "2", "3" → heading_format is "{n}"
  - If candidate headings show "CHAPTER 1", "CHAPTER 2" → heading_format is "CHAPTER {n}"
  - If candidate headings show "Chapter 1", "Chapter 2" → heading_format is "Chapter {n}"
  - If candidate headings show "Part I", "Part II" → heading_format is "Part {n}"
- reasoning: Why you believe this pattern exists

IMPORTANT:
- Output the FULL expected range, not just what you see in candidates.
- Look at the actual heading_text in candidate_headings to determine heading_format.
- If you see chapters 1, 2, 3, 5, 6 → output range "1" to "6" (we'll search for all).
- heading_format MUST match what you see in the candidate headings!

Look at:
- The ToC structure (does it have Parts I-V suggesting chapters within?)
- The candidate headings (what chapter numbers appear?)
- Page density (38 chapters across 400 body pages = ~10 pages per chapter)

### named patterns (rarely used)
Only for specific named sections that repeat:
- pattern_type: "named"
- level_name: "conclusion", "epilogue", etc.
- level: Structural depth

## excluded_page_ranges (CRITICAL)
Page ranges to skip entirely during discovery. **Always exclude**:
- Notes/Footnotes section (dense reference text)
- Bibliography section
- Index section (from "Index" ToC entry to end)
- Acknowledgments section
- Photo/Image sections (if clearly separate from text)

Look at the ToC entries to identify back matter sections and their page ranges.

## reasoning
Brief summary of your analysis and why you identified these patterns."""


def build_pattern_prompt(toc_entries, candidate_headings, body_range):
    toc_lines = []
    for e in toc_entries:
        entry_str = f"  p{e.scan_page}: "
        if e.level_name:
            entry_str += f"[{e.level_name}] "
        if e.entry_number:
            entry_str += f"{e.entry_number}. "
        entry_str += e.title or "(untitled)"
        toc_lines.append(entry_str)

    candidate_lines = [f"  p{c.scan_page}: \"{c.heading_text}\""
                       for c in candidate_headings[:100]]  # Limit to avoid token overflow

    if len(candidate_headings) > 100:
        candidate_lines.append(f"  ... and {len(candidate_headings) - 100} more")

    return f"""## ToC Entries (linked to scan pages)
{chr(10).join(toc_lines)}

## Candidate Headings (detected but NOT in ToC)
Body range: pages {body_range[0]}-{body_range[1]}
{chr(10).join(candidate_lines)}

Analyze for sequential patterns (chapters, parts, appendices) and excluded page ranges.
Output the FULL expected range for any patterns - we will search for every entry."""
