from typing import Dict
from PIL import Image

from infra.llm.models import LLMRequest
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.utils.pdf import downsample_for_vision
from pipeline.olm_ocr.schemas import OlmOcrPageOutput
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
) -> LLMRequest:
    page_num = item
    total_toc_pages = toc_range.end_page - toc_range.start_page + 1

    source_image_path = storage.stage("source").load_page_image(page_num)
    ocr_page = storage.stage('olm-ocr').load_page(page_num, schema=OlmOcrPageOutput)

    image = Image.open(source_image_path)
    image = downsample_for_vision(image)

    page_structure_notes = structure_notes_from_finder.get(page_num, None)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(
            page_num=page_num,
            total_toc_pages=total_toc_pages,
            ocr_text=ocr_page.get("text", ""),
            structure_notes=page_structure_notes,
            global_structure=global_structure_from_finder
        )}
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
