import json
from typing import Optional, Tuple
from PIL import Image

from infra.llm.batch_client import LLMRequest
from infra.storage.book_storage import BookStorage
from infra.utils.pdf import downsample_for_vision
from pipeline.ocr.schemas import OCRPageOutput

from .prompts import STAGE2_SYSTEM_PROMPT, build_stage2_user_prompt
from .schemas import build_page_specific_schema


def prepare_stage2_request(
    page_num: int,
    storage: BookStorage,
    model: str,
    total_pages: int,
    stage1_results: dict = None,
) -> Optional[Tuple[LLMRequest, OCRPageOutput]]:
    if stage1_results is None:
        from ..storage import LabelPagesStageStorage
        stage_storage = LabelPagesStageStorage(stage_name='label-pages')
        stage1_results = stage_storage.load_stage1_result(storage, page_num)
        if not stage1_results:
            raise FileNotFoundError(f"Stage 1 results not found for page {page_num}")
    from pipeline.ocr.storage import OCRStageStorage
    ocr_storage = OCRStageStorage(stage_name='ocr')
    ocr_data = ocr_storage.load_selected_page(
        storage,
        page_num,
        include_line_word_data=False
    )

    if not ocr_data:
        raise FileNotFoundError(f"OCR data not found for page {page_num}")

    ocr_page = OCRPageOutput(**ocr_data)

    source_stage = storage.stage('source')
    image_file = source_stage.output_page(page_num, extension='png')

    if not image_file.exists():
        raise FileNotFoundError(f"Source image not found for page {page_num}")

    page_image = Image.open(image_file)
    page_image = downsample_for_vision(page_image)

    response_schema = build_page_specific_schema(ocr_page)

    ocr_blocks_summary = f"{len(ocr_page.blocks)} OCR blocks"
    ocr_text = json.dumps(ocr_page.model_dump(), indent=2)

    user_prompt = build_stage2_user_prompt(
        ocr_blocks_summary=ocr_blocks_summary,
        ocr_text=ocr_text,
        stage1_results=stage1_results,
        current_page=page_num,
        total_pages=total_pages,
    )

    request = LLMRequest(
        id=f"stage2_page_{page_num:04d}",
        model=model,
        messages=[
            {"role": "system", "content": STAGE2_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        images=[page_image],
        response_format=response_schema,
        metadata={
            'page_num': page_num,
            'ocr_page': ocr_page,
            'stage': 'stage2',
        }
    )

    return request, ocr_page
