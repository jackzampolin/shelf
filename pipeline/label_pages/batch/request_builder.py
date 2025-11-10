from typing import Optional
from PIL import Image

from infra.llm.models import LLMRequest
from infra.pipeline.storage.book_storage import BookStorage
from infra.utils.pdf import downsample_for_vision

from .prompts import OBSERVATION_SYSTEM_PROMPT, build_observation_user_prompt
from .schemas import PageStructureObservation


def prepare_stage1_request(
    item: int,
    storage: BookStorage,
    model: str,
    total_pages: int,
) -> Optional[LLMRequest]:
    """
    Build LLMRequest for one page.

    Args:
        item: Page number to process
        storage: BookStorage (from closure)
        model: Model name
        total_pages: Total page count for position calculation

    Returns:
        LLMRequest for this page
    """
    page_num = item  # 'item' is page number for this stage
    source_stage = storage.stage('source')
    ocr_pages_stage = storage.stage('ocr-pages')

    # Load page image
    image_file = source_stage.output_dir / f"page_{page_num:04d}.png"
    if not image_file.exists():
        raise FileNotFoundError(f"Source image not found for page {page_num}")

    page_image = Image.open(image_file)
    page_image = downsample_for_vision(page_image, max_payload_kb=300)

    # Load OCR text from ocr-pages output
    ocr_text = ""
    try:
        from pipeline.ocr_pages.schemas import OcrPagesPageOutput

        ocr_data = ocr_pages_stage.load_page(page_num, schema=OcrPagesPageOutput)
        ocr_text = ocr_data.get('text', '')
    except FileNotFoundError:
        # OCR-Pages should have been validated in before(), but handle gracefully
        ocr_text = "(OCR-Pages output not found for this page)"
    except Exception as e:
        ocr_text = f"(Error loading OCR text: {str(e)})"

    response_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "page_structure_observation",
            "strict": True,
            "schema": PageStructureObservation.model_json_schema()
        }
    }

    user_prompt = build_observation_user_prompt(ocr_text=ocr_text)

    return LLMRequest(
        id=f"page_observation_{page_num:04d}",
        model=model,
        messages=[
            {"role": "system", "content": OBSERVATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        images=[page_image],
        response_format=response_schema,
        metadata={
            'page_num': page_num,
            'stage': 'stage1',
        }
    )
