"""Vision-based page labeling: prompts, request preparation, and dynamic schemas."""

import json
from typing import Optional, Tuple
from PIL import Image

from infra.llm.batch_client import LLMRequest
from infra.storage.book_storage import BookStorage
from infra.utils.pdf import downsample_for_vision
from pipeline.ocr.schemas import OCRPageOutput

from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import build_page_specific_schema


def prepare_label_request(
    page_num: int,
    storage: BookStorage,
    model: str,
    total_pages: int,
    prev_page_number: str = None,
) -> Optional[Tuple[LLMRequest, OCRPageOutput]]:
    """
    Prepare a single labeling LLM request.

    Loads OCR data and source image, generates page-specific schema,
    and builds the LLM request with vision input.

    Args:
        page_num: Page number (1-indexed)
        storage: BookStorage instance
        model: Vision model to use
        total_pages: Total pages in book (for prompt context)
        prev_page_number: Previous page's printed number for sequence validation

    Returns:
        Tuple of (LLMRequest, OCRPageOutput) or None if page can't be loaded

    Raises:
        Exception: If OCR data or source image is missing
    """
    # Load OCR data using OCR stage's selection map
    # Strip line/word data to reduce token cost (we only need paragraph text)
    from pipeline.ocr.storage import OCRStageStorage
    ocr_storage = OCRStageStorage(stage_name='ocr')
    ocr_data = ocr_storage.load_selected_page(
        storage,
        page_num,
        include_line_word_data=False  # Only need paragraph text, not line/word bboxes
    )

    if not ocr_data:
        raise FileNotFoundError(f"OCR data not found for page {page_num}")

    ocr_page = OCRPageOutput(**ocr_data)

    # Load source image
    source_stage = storage.stage('source')
    image_file = source_stage.output_page(page_num, extension='png')

    if not image_file.exists():
        raise FileNotFoundError(f"Source image not found for page {page_num}")

    page_image = Image.open(image_file)
    page_image = downsample_for_vision(page_image)

    # Generate page-specific schema (constrains block count)
    response_schema = build_page_specific_schema(ocr_page)

    # Load book metadata for context
    metadata = storage.load_metadata()

    # Build OCR text for prompt (simplified JSON)
    ocr_text = json.dumps(ocr_page.model_dump(), indent=2)

    # Build page-specific prompt
    user_prompt = build_user_prompt(
        ocr_page=ocr_page.model_dump(),
        ocr_text=ocr_text,
        current_page=page_num,
        total_pages=total_pages,
        book_metadata=metadata,
        prev_page_number=prev_page_number,
    )

    # Create LLM request (multimodal) with page-specific schema
    request = LLMRequest(
        id=f"page_{page_num:04d}",
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        images=[page_image],  # Vision input
        response_format=response_schema,  # Page-specific constraints!
        metadata={
            'page_num': page_num,
            'ocr_page': ocr_page,
        }
    )

    return request, ocr_page
