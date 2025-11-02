from typing import Optional, Tuple
from PIL import Image

from infra.llm.batch_client import LLMRequest
from infra.storage.book_storage import BookStorage
from infra.utils.pdf import downsample_for_vision
from pipeline.ocr.schemas import OCRPageOutput

from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import build_page_specific_schema


def prepare_correction_request(
    page_num: int,
    storage: BookStorage,
    model: str,
    total_pages: int,
) -> Optional[Tuple[LLMRequest, OCRPageOutput]]:
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

    metadata = storage.load_metadata()

    user_prompt = build_user_prompt(
        page_num=page_num,
        total_pages=total_pages,
        book_metadata=metadata,
        ocr_data=ocr_page.model_dump()
    )

    request = LLMRequest(
        id=f"page_{page_num:04d}",
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        images=[page_image],
        response_format=response_schema,
        metadata={
            'page_num': page_num,
            'ocr_page': ocr_page,
        }
    )

    return request, ocr_page
