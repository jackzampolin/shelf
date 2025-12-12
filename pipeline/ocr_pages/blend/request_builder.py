"""
Build LLM requests for diff-based OCR correction.

Uses Mistral as base, asks LLM for corrections only.
"""

from infra.llm.models import LLMRequest
from .prompt import BLEND_SYSTEM_PROMPT, BLEND_USER_PROMPT, CORRECTIONS_JSON_SCHEMA


def prepare_blend_request(item: int, storage) -> LLMRequest:
    """Build request for diff-based blend."""
    ocr_stage = storage.stage("ocr-pages")

    # Load Mistral output (authoritative base)
    try:
        mistral_data = ocr_stage.load_page(item, subdir="mistral")
        mistral_text = mistral_data.get("markdown", "")
    except FileNotFoundError:
        mistral_text = ""

    # Load Paddle output (comparison)
    try:
        paddle_data = ocr_stage.load_page(item, subdir="paddle")
        paddle_text = paddle_data.get("text", "")
    except FileNotFoundError:
        paddle_text = ""

    if not mistral_text and not paddle_text:
        raise ValueError(f"No OCR data for page {item:04d}")

    # Load source image for verification
    source_image = storage.source().load_page_image(item, downsample=True, max_payload_kb=800)

    return LLMRequest(
        id=f"page_{item:04d}",
        messages=[
            {"role": "system", "content": BLEND_SYSTEM_PROMPT},
            {"role": "user", "content": BLEND_USER_PROMPT.format(
                mistral_text=mistral_text,
                paddle_text=paddle_text,
            )},
        ],
        images=[source_image],
        response_format=CORRECTIONS_JSON_SCHEMA,
        temperature=0.1,
        timeout=600,  # 10 minutes - vision + structured output can be slow
    )
