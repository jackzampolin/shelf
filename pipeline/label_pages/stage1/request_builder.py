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
    source_stage = storage.stage('source')
    tesseract_stage = storage.stage('tesseract')

    # Load page image
    image_file = source_stage.output_page(page_num, extension='png')
    if not image_file.exists():
        raise FileNotFoundError(f"Source image not found for page {page_num}")

    page_image = Image.open(image_file)
    page_image = downsample_for_vision(page_image, max_payload_kb=300)

    # Load OCR text from tesseract output
    ocr_text = ""
    tesseract_output_file = tesseract_stage.output_page(page_num, extension='json')
    if tesseract_output_file.exists():
        from infra.storage.schemas import load_page
        from pipeline.tesseract.schemas import TesseractPageOutput

        tesseract_data = load_page(tesseract_output_file, TesseractPageOutput)
        ocr_text = tesseract_data.full_text
    else:
        # Tesseract should have been validated in before(), but handle gracefully
        ocr_text = "(Tesseract output not found for this page)"

    response_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "stage1_boundary_detection",
            "strict": True,
            "schema": Stage1LLMResponse.model_json_schema()
        }
    }

    # Calculate position percentage
    position_pct = int((page_num / total_pages) * 100)

    user_prompt = build_stage1_user_prompt(
        position_pct=position_pct,
        ocr_text=ocr_text,
    )

    return LLMRequest(
        id=f"stage1_page_{page_num:04d}",
        model=model,
        messages=[
            {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        images=[page_image],
        response_format=response_schema,
        metadata={
            'page_num': page_num,
            'stage': 'stage1',
        }
    )
