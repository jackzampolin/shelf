from infra.llm.models import LLMRequest
from ..schemas.unified import UnifiedExtractionOutput
from .prompt import SYSTEM_PROMPT, USER_PROMPT


def prepare_unified_request(item: int, storage) -> LLMRequest:
    ocr_stage = storage.stage("ocr-pages")

    try:
        blend_data = ocr_stage.load_page(item, subdir="blend")
        blended_text = blend_data.get("markdown", "")
    except FileNotFoundError:
        blended_text = ""
    except Exception as e:
        raise ValueError(f"Failed to load blended OCR for page {item:04d}: {e}")

    if not blended_text:
        raise ValueError(f"No OCR data for page {item:04d}")

    return LLMRequest(
        id=f"page_{item:04d}",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT.format(blended_text=blended_text)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "unified_extraction",
                "strict": True,
                "schema": UnifiedExtractionOutput.model_json_schema()
            }
        },
        temperature=0.1,
        timeout=300
    )
