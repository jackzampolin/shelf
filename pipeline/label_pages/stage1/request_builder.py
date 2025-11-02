"""Stage 1: Page-level structural analysis with 3-image context."""

from typing import Optional
from PIL import Image

from infra.llm.batch_client import LLMRequest
from infra.storage.book_storage import BookStorage
from infra.utils.pdf import downsample_for_vision

from .prompts import STAGE1_SYSTEM_PROMPT, build_stage1_user_prompt
from .schemas import Stage1LLMResponse


def prepare_stage1_request(
    page_num: int,
    storage: BookStorage,
    model: str,
    total_pages: int,
) -> Optional[LLMRequest]:
    """
    Prepare Stage 1 vision request with 3-image context (prev, current, next).

    Args:
        page_num: Current page number to analyze
        storage: Book storage
        model: Vision model to use
        total_pages: Total pages in book

    Returns:
        LLMRequest with 3 images or None if images unavailable
    """
    source_stage = storage.stage('source')

    # Determine prev/next page numbers (handle boundaries)
    prev_page_num = max(1, page_num - 1) if page_num > 1 else page_num
    next_page_num = min(total_pages, page_num + 1) if page_num < total_pages else page_num

    # Load three images
    # Reduce max_payload_kb since we're sending 3 images (3 * 300KB ~= 900KB total)
    images = []
    for p in [prev_page_num, page_num, next_page_num]:
        image_file = source_stage.output_page(p, extension='png')
        if not image_file.exists():
            raise FileNotFoundError(f"Source image not found for page {p}")

        page_image = Image.open(image_file)
        page_image = downsample_for_vision(page_image, max_payload_kb=300)
        images.append(page_image)

    # Build response schema from Stage1LLMResponse
    response_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "stage1_structural_analysis",
            "strict": True,
            "schema": Stage1LLMResponse.model_json_schema()
        }
    }

    user_prompt = build_stage1_user_prompt(
        current_page_num=page_num,
        prev_page_num=prev_page_num,
        next_page_num=next_page_num,
        total_pages=total_pages,
    )

    request = LLMRequest(
        id=f"stage1_page_{page_num:04d}",
        model=model,
        messages=[
            {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        images=images,  # 3 images: [prev, current, next]
        response_format=response_schema,
        metadata={
            'page_num': page_num,
            'stage': 'stage1',
        }
    )

    return request
