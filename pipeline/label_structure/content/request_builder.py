"""
Request builder for content flow pass.

Text-only: OCR + margin + body → content flow analysis.
No vision needed - cheapest pass.
"""

from typing import Optional
import json

from infra.llm.models import LLMRequest
from infra.pipeline.storage.book_storage import BookStorage

from .prompts import build_content_user_prompt
from .schemas import ContentObservation


def prepare_content_request(
    item: int,
    storage: BookStorage,
    model: str,
    stage_name: str,
    **kwargs
) -> Optional[LLMRequest]:
    """
    Build LLMRequest for content flow pass.

    Args:
        item: Page number to process
        storage: BookStorage
        model: Model name (can use cheaper text-only model)
        stage_name: Name of the label-structure stage
        **kwargs: Unused (for compatibility)

    Returns:
        LLMRequest for content observation
    """
    page_num = item
    ocr_pages_stage = storage.stage('ocr-pages')
    label_structure_stage = storage.stage(stage_name)

    # Load OCR text
    ocr_text = ""
    try:
        from pipeline.ocr_pages.schemas import OcrPagesPageOutput
        ocr_data = ocr_pages_stage.load_page(page_num, schema=OcrPagesPageOutput)
        ocr_text = ocr_data.get('text', '')
    except FileNotFoundError:
        ocr_text = "(OCR text not found for this page)"
    except Exception as e:
        ocr_text = f"(Error loading OCR text: {str(e)})"

    # Load margin pass output
    margin_file = label_structure_stage.output_dir / "margin" / f"page_{page_num:04d}.json"
    if not margin_file.exists():
        raise FileNotFoundError(f"Margin pass output not found for page {page_num}")

    with open(margin_file, 'r') as f:
        margin_data = json.load(f)

    # Load body pass output
    body_file = label_structure_stage.output_dir / "body" / f"page_{page_num:04d}.json"
    if not body_file.exists():
        raise FileNotFoundError(f"Body pass output not found for page {page_num}")

    with open(body_file, 'r') as f:
        body_data = json.load(f)

    # Response schema
    response_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "content_observation",
            "strict": True,
            "schema": ContentObservation.model_json_schema()
        }
    }

    user_prompt = build_content_user_prompt(ocr_text, margin_data, body_data)

    return LLMRequest(
        id=f"content_{page_num:04d}",
        model=model,
        messages=[
            {"role": "user", "content": user_prompt}
        ],
        images=[],  # No images - text-only
        response_format=response_schema,
        timeout=20,  # Content: text-only, fastest pass, avg 5s, p95 9s
        metadata={
            'page_num': page_num,
            'pass': 'content',
        }
    )
