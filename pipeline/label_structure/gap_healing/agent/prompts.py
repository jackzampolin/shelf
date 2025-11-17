import json
from typing import Dict, List


HEALER_SYSTEM_PROMPT = """You are a page number gap healing expert for scanned books.

**Your role:**
Analyze page number sequences in scanned books and fix detection errors. You work with:
- OCR-detected page numbers (may be wrong)
- Page metadata (headers, footers, headings)
- Sequence context (surrounding pages)
- Visual inspection when needed

**Available tools:**
1. **get_page_metadata(page_num)**: Read full metadata for pages outside the cluster (FREE)
2. **view_page_image(page_num)**: Visual inspection when metadata is ambiguous (~$0.001/page)
   - WORKFLOW: Document observations of current page BEFORE loading next
   - One page at a time - previous page removed when you load next
3. **heal_page(scan_page, page_number, ...)**: Fix ONE page's number/chapter (call multiple times for multi-page gaps)
4. **finish_cluster(summary, pages_healed)**: Mark cluster complete (REQUIRED at end)

**Core principles:**
- **Be conservative**: Only fix when confident
- **Use vision liberally**: It's cheap (~$0.001/page) and prevents errors
- **Reason explicitly**: Show your analysis in reasoning field
- **One heal_page per page**: Call multiple times for multi-page clusters
- **Always finish**: Call finish_cluster even if no healing needed

**Common issue patterns:**
- Backward jumps: Usually chapter numbers detected as page numbers
- OCR errors: Character substitutions (O→0, I→1, decimal artifacts)
- Structural gaps: Blank/unnumbered pages at chapter boundaries
- Gap mismatches: Missing pages from scan or numbering restarts

**Important context about scans:**
- Books often have blank divider pages between parts/chapters
- These blank pages are frequently not scanned
- This means page number sequences may have gaps
- Always examine surrounding page numbers to infer correct value
"""


def build_healer_user_prompt(cluster: Dict, page_data_map: Dict[int, Dict], sequence_context: List[Dict]) -> str:
    cluster_type = cluster['type']
    scan_pages = cluster['scan_pages']

    page_data_section = "**Page Data (Full JSON for cluster pages):**\n```json\n"
    for page_num in scan_pages:
        if page_num in page_data_map:
            page_data_section += f"// Page {page_num}\n"
            page_data_section += json.dumps(page_data_map[page_num], indent=2)
            page_data_section += "\n\n"
    page_data_section += "```\n\n"

    sequence_section = "**Sequence Context (from report.csv):**\n```\n"
    sequence_section += "Page | Detected | Status          | Gap | Expected\n"
    sequence_section += "-----|----------|-----------------|-----|----------\n"
    for row in sequence_context:
        page = row['page_num']
        detected = row.get('page_num_value', '—')
        status = row.get('sequence_status', 'unknown')
        gap = row.get('sequence_gap', '0')
        expected = row.get('expected_value', '—')

        marker = " ← CLUSTER" if page in scan_pages else ""

        sequence_section += f"{page:4} | {detected:8} | {status:15} | {gap:3} | {expected:8}{marker}\n"
    sequence_section += "```\n\n"

    type_guidance = ""

    if cluster_type == "backward_jump":
        type_guidance = """**Analysis Task: Backward Jump**

This cluster shows a backward jump (page number decreased when it should increase).
Typical cause: Chapter number detected as page number instead of actual page number.

**Step 1: Examine the sequence context below**
- Find prev_page, current_page(s), and next_page detected numbers
- Calculate what the gap tells you about missing pages

**Step 2: Infer correct page number**
Method: Use the NEXT page's detected number to work backward

Example from sequence table:
```
Page 84: detected=71
Page 85: detected=9   ← THIS is the backward jump (CLUSTER PAGE)
Page 86: detected=73
```

Analysis:
- Next page (86) shows 73
- Therefore current page (85) should be: 73 - 1 = **72**
- The detected "9" is likely a chapter number

**Step 3: Check for chapter markers**
- Look at the page_data JSON below for heading fields
- If heading shows "Chapter 9" or "IX" or similar: This is a chapter title page
- Extract chapter_marker: {chapter_num: 9, chapter_title: "...", ...}

**Step 4: Account for missing blank pages**
- If next_page - prev_page = 2 (like 73 - 71 = 2):
  * Only 1 page between them in the scan
  * No missing blank pages
  * Current page = prev + 1 = 72
- If next_page - prev_page = 3 (like 74 - 71 = 3):
  * 2 pages between them in the scan (should be page 85 and 86)
  * One blank page was not scanned
  * Current page (85) might be 72 or 73 depending on which blank is missing
  * Use headings/vision to determine

**Step 5: Heal the page(s)**
- Call heal_page for EACH page needing correction
- Include your reasoning showing the calculation
- Extract chapter_marker if this is a chapter title page
"""

    elif cluster_type == "ocr_error":
        raw_value = cluster.get('raw_value', 'N/A')
        type_guidance = f"""**OCR Error Analysis:**

This cluster has an unparseable page number value: "{raw_value}"

**Common OCR substitutions:**
- "O" → "0" at end (e.g., "13o" → "130")
- "I" → "1" anywhere (e.g., "30I" → "301", "3I2" → "312")
- Decimal artifacts (e.g., "1.11" → "111")

**What to check:**
1. Look at the raw_value and determine likely intended number
2. Verify with sequence context (does substitution make sense?)
3. Consider using vision if the pattern is unclear
"""

    elif cluster_type == "structural_gap":
        gap_size = cluster.get('gap_size', 'N/A')
        type_guidance = f"""**Structural Gap Analysis:**

This cluster has a gap_{gap_size} - potentially intentional book design.

**What to check:**
1. Look at headings - do they show PART/CHAPTER markers?
2. Check headers/footers for context
3. Gap_3 to gap_6 often indicate:
   - Blank pages at chapter/part boundaries
   - Unnumbered photo sections
   - Intentional design breaks

**Possible actions:**
- Accept as-is if it looks intentional
- Use vision to check if page numbers are present but undetected
- Fix only if you find clear evidence of detection failure
"""

    elif cluster_type == "gap_mismatch":
        type_guidance = """**Gap Mismatch Analysis:**

This cluster has a mismatch between expected and actual gap size.

**What to check:**
1. Are pages missing from the scan? (look at total_pages)
2. Did OCR fail to detect page numbers that are actually there?
3. Is there a numbering restart (e.g., appendix restarts at 1)?
4. Use vision to inspect pages and determine cause
"""

    prompt = f"""Analyze and heal cluster: **{cluster['cluster_id']}**

**Cluster:** {cluster_type} | Pages: {', '.join(map(str, scan_pages))} | Priority: {cluster.get('priority', 'medium')}

{type_guidance}

{sequence_section}

{page_data_section}

**Your Task:**
1. Follow the analysis steps above for this cluster type
2. Use tools to gather additional information if needed
3. For EACH page requiring correction: call heal_page(scan_page, page_number, reasoning, ...)
4. When analysis complete: call finish_cluster(summary, pages_healed)

**Remember:**
- Call heal_page ONCE per page (multiple times for multi-page clusters)
- Call finish_cluster even if no healing needed
- Show your calculation/reasoning in each heal_page call

Begin analysis.
"""

    return prompt
