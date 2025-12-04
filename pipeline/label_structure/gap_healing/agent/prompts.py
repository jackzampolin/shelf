import json
from typing import Dict, List


HEALER_SYSTEM_PROMPT = """You fix page number detection errors in scanned books.

You have tools to:
- **get_page_metadata(page_num)**: Read metadata for context pages (free)
- **view_page_image(page_num)**: Visual inspection (~$0.001/page) - document current page before loading next
- **heal_page(scan_page, page_number, reasoning)**: Fix one page's number
- **finish_cluster(summary, pages_healed)**: Mark complete (required)

Key patterns:
- Backward jumps: Chapter number detected as page number (e.g., "9" instead of "72")
- OCR errors: Character substitution (O→0, I→1)
- Gaps: Missing scans or unnumbered pages

Always use surrounding page numbers to infer correct values. Call finish_cluster even if no healing needed."""


def build_healer_user_prompt(cluster: Dict, page_data_map: Dict[int, Dict], sequence_context: List[Dict]) -> str:
    cluster_type = cluster['type']
    scan_pages = cluster['scan_pages']

    page_data_section = "**Page Data:**\n```json\n"
    for page_num in scan_pages:
        if page_num in page_data_map:
            page_data_section += f"// Page {page_num}\n"
            page_data_section += json.dumps(page_data_map[page_num], indent=2)
            page_data_section += "\n\n"
    page_data_section += "```\n\n"

    sequence_section = "**Sequence Context:**\n```\n"
    sequence_section += "Page | Detected | Status          | Expected\n"
    sequence_section += "-----|----------|-----------------|----------\n"
    for row in sequence_context:
        page = row['page_num']
        detected = row.get('page_num_value', '—') or '—'
        status = row.get('sequence_status', 'unknown')
        expected = row.get('expected_value', '—') or '—'
        marker = " ← CLUSTER" if page in scan_pages else ""
        sequence_section += f"{page:4} | {detected:8} | {status:15} | {expected:8}{marker}\n"
    sequence_section += "```\n\n"

    type_guidance = _get_type_guidance(cluster_type, cluster)

    return f"""Analyze cluster: **{cluster['cluster_id']}** ({cluster_type})

Pages: {', '.join(map(str, scan_pages))}

{type_guidance}

{sequence_section}
{page_data_section}

Call heal_page for each page needing correction, then finish_cluster."""


def _get_type_guidance(cluster_type: str, cluster: Dict) -> str:
    if cluster_type == "backward_jump":
        return """**Backward Jump**: Page number decreased unexpectedly.

Likely cause: Chapter number detected as page number.

To fix:
1. Look at NEXT page's detected number
2. Current page = next_page - 1
3. Call heal_page with corrected number"""

    elif cluster_type == "ocr_error":
        raw_value = cluster.get('raw_value', 'N/A')
        return f"""**OCR Error**: Unparseable value "{raw_value}"

Common substitutions: O→0, I→1, decimal artifacts (1.11→111)

To fix:
1. Determine intended number from raw value
2. Verify with sequence context
3. Use vision if unclear"""

    elif cluster_type == "structural_gap":
        gap_size = cluster.get('gap_size', 'N/A')
        return f"""**Structural Gap**: {gap_size} page gap detected.

Often intentional: chapter boundaries, photo sections, blank pages.

To fix:
1. Check if numbers are present but undetected (use vision)
2. If intentional gap, call finish_cluster with no healing"""

    elif cluster_type == "gap_mismatch":
        actual = cluster.get('actual_gap', '?')
        expected = cluster.get('expected_gap', '?')
        return f"""**Gap Mismatch**: Expected {expected} page gap, found {actual}.

Causes: Missing scans, numbering restart, detection failure.

To fix:
1. Use vision to inspect pages
2. Determine if pages missing or numbers undetected"""

    elif cluster_type == "isolated":
        return """**Isolated**: No surrounding context to infer correct number.

To fix:
1. Use vision to check page for visible number
2. If no number visible, may be unnumbered page - finish with no healing"""

    elif cluster_type == "edge_gap":
        return """**Edge Gap**: Gap at start/end of sequence with incomplete context.

To fix:
1. Use available context (prev or next page)
2. Use vision if needed to verify"""

    elif cluster_type == "multi_page_jump":
        return """**Multi-Page Jump**: Large unexpected gap in sequence.

Causes: Missing scans, section boundaries, numbering restart.

To fix:
1. Use vision to inspect pages
2. Determine actual page numbers or confirm intentional gap"""

    else:
        return f"""**{cluster_type}**: Analyze the sequence context and page data to determine correct page numbers."""
