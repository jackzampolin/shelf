from typing import Dict, List, Optional

from infra.llm.models import LLMRequest
from infra.pipeline.storage.book_storage import BookStorage

from .prompts import EVALUATION_SYSTEM_PROMPT, build_evaluation_prompt
from ..schemas import DiscoveredPattern


def _get_nearby_toc_context(candidate: dict, toc_entries_by_page: Dict[int, str], total_pages: int = 0) -> str:
    if not toc_entries_by_page:
        return ""

    preceding_page = candidate.get("preceding_toc_page")
    following_page = candidate.get("following_toc_page")
    candidate_page = candidate["scan_page"]

    # Calculate back matter threshold (last 15% of book)
    back_matter_threshold = int(total_pages * 0.85) if total_pages else 0

    context_parts = []

    if preceding_page and preceding_page in toc_entries_by_page:
        preceding_title = toc_entries_by_page[preceding_page]
        warning = ""
        if back_matter_threshold and preceding_page >= back_matter_threshold:
            warning = " ⚠️ SUSPICIOUS: May be footnote reference, not actual chapter"
        context_parts.append(f"- PRECEDING ToC entry (p{preceding_page}): \"{preceding_title}\"{warning}")

    if following_page and following_page in toc_entries_by_page:
        following_title = toc_entries_by_page[following_page]
        warning = ""
        if back_matter_threshold and following_page >= back_matter_threshold:
            warning = " ⚠️ SUSPICIOUS: May be footnote reference, not actual chapter"
        context_parts.append(f"- FOLLOWING ToC entry (p{following_page}): \"{following_title}\"{warning}")

    if context_parts:
        return "\n".join(context_parts)
    return ""


def prepare_evaluation_request(
    item: int,
    candidate: dict,
    storage: BookStorage,
    patterns: List[DiscoveredPattern],
    toc_summary: str,
    toc_entries_by_page: Optional[Dict[int, str]] = None,
) -> LLMRequest:
    """Prepare evaluation request for a candidate heading.

    Args:
        item: The candidate index (used for unique ID)
        candidate: The candidate heading dict
        storage: Book storage
        patterns: Discovered structural patterns
        toc_summary: ToC summary context
        toc_entries_by_page: Map of page numbers to ToC entry titles
    """
    toc_entries_by_page = toc_entries_by_page or {}

    image = storage.source().load_page_image(
        page_num=candidate["scan_page"],
        downsample=True,
        max_payload_kb=400
    )

    from ..schemas import CandidateHeading
    candidate_obj = CandidateHeading(**candidate)

    # Get total pages for back matter threshold calculation
    total_pages = storage.load_metadata().get('total_pages', 0)
    nearby_toc_context = _get_nearby_toc_context(candidate, toc_entries_by_page, total_pages)

    user_prompt = build_evaluation_prompt(
        candidate=candidate_obj,
        patterns=patterns,
        toc_context=toc_summary,
        nearby_toc_entries=nearby_toc_context
    )

    return LLMRequest(
        id=f"heading_{item:04d}",
        messages=[
            {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        images=[image],
        temperature=0.0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "heading_evaluation",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "include": {"type": "boolean"},
                        "title": {"type": ["string", "null"]},
                        "level": {"type": ["integer", "null"]},
                        "entry_number": {"type": ["string", "null"]},
                        "reasoning": {"type": "string"}
                    },
                    "required": ["include", "reasoning"],
                    "additionalProperties": False
                }
            }
        },
        timeout=120
    )
