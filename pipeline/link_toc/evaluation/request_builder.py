from infra.llm.models import LLMRequest
from infra.pipeline.storage.book_storage import BookStorage

from .prompts import EVALUATION_SYSTEM_PROMPT, build_evaluation_prompt


def prepare_evaluation_request(
    item: dict,
    storage: BookStorage,
    observations: list,
    toc_summary: str,
) -> LLMRequest:
    """Build LLM request to evaluate a candidate heading."""

    candidate = item  # item is a CandidateHeading dict

    # Load page image
    image = storage.source().load_page_image(
        page_num=candidate["scan_page"],
        downsample=True,
        max_payload_kb=400
    )

    # Build prompt with observations context
    from ..schemas import CandidateHeading
    candidate_obj = CandidateHeading(**candidate)

    user_prompt = build_evaluation_prompt(
        candidate=candidate_obj,
        observations=observations,
        toc_context=toc_summary
    )

    return LLMRequest(
        id=f"heading_{candidate['scan_page']:04d}",
        messages=[
            {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        images=[image],
        temperature=0.0,
        response_format={"type": "json_object"},
        timeout=120
    )
