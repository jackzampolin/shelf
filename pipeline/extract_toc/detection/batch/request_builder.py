from typing import Optional, Dict
from PIL import Image

from infra.llm.models import LLMRequest
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.utils.pdf import downsample_for_vision

from ...schemas import PageRange
from ..prompts import SYSTEM_PROMPT, build_user_prompt


def prepare_toc_request(
    item: int,
    storage: BookStorage,
    model: str,
    toc_range: PageRange,
    structure_notes_from_finder: Dict[int, str],
    global_structure_from_finder: dict,
    logger: PipelineLogger
) -> Optional[LLMRequest]:
    page_num = item
    total_toc_pages = toc_range.end_page - toc_range.start_page + 1

    source_storage = storage.stage("source")
    ocr_pages_storage = storage.stage('ocr-pages')

    from pipeline.ocr_pages.schemas import OcrPagesPageOutput
    page_data = ocr_pages_storage.load_page(page_num, schema=OcrPagesPageOutput)

    if not page_data:
        logger.error(f"  Page {page_num}: OCR data not found in ocr-pages stage")
        return None

    ocr_text = page_data.get("text", "")

    # Load page image
    page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

    if not page_file.exists():
        logger.error(f"  Page {page_num}: Source image not found: {page_file}")
        return None

    image = Image.open(page_file)
    image = downsample_for_vision(image)

    page_structure_notes = structure_notes_from_finder.get(page_num, None)

    user_prompt = build_user_prompt(
        page_num=page_num,
        total_toc_pages=total_toc_pages,
        ocr_text=ocr_text,
        structure_notes=page_structure_notes,
        global_structure=global_structure_from_finder
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    return LLMRequest(
        id=f"page_{page_num:04d}",
        model=model,
        messages=messages,
        images=[image],
        temperature=0.0,
        response_format={"type": "json_object"},
        timeout=300,
        metadata={"page_num": page_num}
    )
