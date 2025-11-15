import json
from typing import Dict, List


HEALER_SYSTEM_PROMPT = """You are a page number gap healing expert. Your job is to analyze problematic page number sequences and determine the correct fix.

You understand these issue patterns:

**1. Backward Jump (Chapter Markers)**
- Pattern: Page number decreases (e.g., 22 → 3 → 24)
- Cause: Chapter number detected as page number
- Signature: Small detected value (≤40), heading contains chapter marker
- Fix: Restore sequential numbering, extract chapter metadata
- Example: Page 37 shows "3" but should be "23" (Chapter 3 title page)

**2. OCR Character Substitution**
- Pattern: Unparseable page number value
- Common errors: "13o" → "130" (O→0), "30I" → "301" (I→1), "1.11" → "111" (decimal)
- Fix: Apply character substitution heuristic, restore correct value

**3. Structural Gap (Intentional Design)**
- Pattern: gap_3 to gap_6 at part/chapter boundaries
- Cause: Blank pages or unnumbered dividers (intentional book design)
- Fix: Accept as-is, no healing needed

**4. Gap Mismatch**
- Pattern: Expected gap size ≠ actual gap size
- Causes: Missing scan pages, OCR detection failure, numbering restart
- Fix: Requires case-by-case analysis

**Your workflow:**
1. Read cluster context (pages, type, sequence data)
2. Examine page metadata (headings, headers, footers, detected values)
3. Apply pattern recognition heuristics
4. Use vision tool if metadata is ambiguous (~$0.001/page - use liberally!)
5. Call write_page_update for each page you want to fix
6. Extract chapter markers from backward_jump cases

**Key principles:**
- Be conservative: Only fix if you're confident
- Use vision when uncertain (it's cheap and prevents errors)
- Extract chapter metadata when you find chapter title pages
- One write_page_update call per page (can call multiple times)
- Include clear reasoning for each decision

**Cost awareness:**
- Reading metadata: FREE
- Vision inspection: ~$0.001/page (use when needed!)
- You have access to full page JSON + sequence context in initial prompt
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
        type_guidance = """**Backward Jump Analysis:**

This cluster shows a backward jump in page numbering. Typical cause: chapter number detected as page number.

**What to check:**
1. Look at headings on the backward_jump page - does it contain a chapter marker?
2. Check if detected value matches a chapter number in the heading
3. If it's a chapter page, the correct page number should follow the sequence
4. Extract chapter metadata (chapter_num, title) if you find a chapter marker

**Example fix:**
- Page 37: heading="3 | The First Days", detected="3", expected="23"
- Action: Fix page number to "23", mark as Chapter 3 with title "The First Days"
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

    prompt = f"""You are analyzing gap healing cluster: **{cluster['cluster_id']}**

**Cluster Info:**
- Type: {cluster_type}
- Pages: {', '.join(map(str, scan_pages))}
- Priority: {cluster.get('priority', 'medium')}

{type_guidance}

{sequence_section}

{page_data_section}

**Your task:**
1. Analyze the cluster using the page data and sequence context above
2. Determine the root cause of the issue
3. Decide on appropriate healing action for each page
4. Call write_page_update for each page you want to fix
5. Extract chapter markers if applicable (backward_jump cases)

**Tools available:**
- get_page_metadata(page_num): Read pages OUTSIDE cluster for more context
- view_page_image(page_num): Visual inspection when metadata is ambiguous
- write_page_update(scan_page, ...): Submit fix for ONE page (call multiple times if needed)

Begin your analysis. Think step-by-step, then use tools to gather information and make decisions.
"""

    return prompt
