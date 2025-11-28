import json
from infra.llm.models import LLMRequest
from ..schemas.unified import UnifiedExtractionOutput
from .prompt import UNIFIED_EXTRACTION_PROMPT


def prepare_unified_request(
    item: int,
    storage,
) -> LLMRequest:
    """Build LLM request for unified structure + annotations extraction.

    Uses blended OCR as the sole input source. The blend stage already
    synthesizes high-quality markdown with headers and page numbers included.
    """
    # Load mechanical output (headings, pattern hints)
    try:
        mechanical_output = storage.stage("label-structure").load_file(
            f"mechanical/page_{item:04d}.json"
        )
    except Exception as e:
        raise ValueError(f"Missing mechanical output for page {item:04d}: {e}")

    headings_json = json.dumps(mechanical_output.get("headings", []), indent=2)
    pattern_hints_json = json.dumps(mechanical_output.get("pattern_hints", {}), indent=2)

    # Load blended OCR (sole source - includes headers/page numbers)
    ocr_stage = storage.stage("ocr-pages")

    try:
        blend_data = ocr_stage.load_page(item, subdir="blend")
        blended_text = blend_data.get("markdown", "")
    except FileNotFoundError:
        blended_text = ""
    except Exception as e:
        raise ValueError(f"Failed to load blended OCR for page {item:04d}: {type(e).__name__}: {e}")

    if not blended_text:
        raise ValueError(f"No OCR data available for page {item:04d} - blend output is empty")

    return LLMRequest(
        id=f"page_{item:04d}",
        messages=[{
            "role": "user",
            "content": UNIFIED_EXTRACTION_PROMPT.format(
                blended_text=blended_text,
                headings_json=headings_json,
                pattern_hints_json=pattern_hints_json
            )}],
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
