import json
from infra.llm.models import LLMRequest
from infra.ocr import filter_ocr_quality
from ..schemas.annotations import AnnotationsOutput
from .prompt import ANNOTATIONS_EXTRACTION_PROMPT


def prepare_annotations_request(
    item: int,
    storage,
) -> LLMRequest:
    # Load mechanical output with error handling
    try:
        mechanical_output = storage.stage("label-structure").load_file(
            f"mechanical/page_{item:04d}.json"
        )
    except Exception as e:
        raise ValueError(f"Missing mechanical output for page {item:04d}: {e}")

    # Load structure output with error handling
    try:
        structure_output = storage.stage("label-structure").load_file(
            f"structure/page_{item:04d}.json"
        )
    except Exception as e:
        raise ValueError(f"Missing structure output for page {item:04d}: {e}")

    headings_json = json.dumps(mechanical_output.get("headings", []), indent=2)
    pattern_hints_json = json.dumps(mechanical_output.get("pattern_hints", {}), indent=2)
    structure_json = json.dumps({
        "header": structure_output.get("header", {}),
        "footer": structure_output.get("footer", {}),
        "page_number": structure_output.get("page_number", {})
    }, indent=2)

    # Load OCR texts with error handling
    try:
        mistral_text = storage.stage("mistral-ocr").load_page(item).get("markdown", "")
    except Exception:
        mistral_text = ""

    try:
        olm_text = storage.stage("olm-ocr").load_page(item).get("text", "")
    except Exception:
        olm_text = ""

    try:
        paddle_text = storage.stage("paddle-ocr").load_page(item).get("text", "")
    except Exception:
        paddle_text = ""

    # Filter out low-quality OCR output (e.g., PADDLE hallucinations on TOC/index pages)
    ocr_filtered = filter_ocr_quality(mistral_text, olm_text, paddle_text)

    return LLMRequest(
        id=f"page_{item:04d}",
        messages=[{
            "role": "user",
            "content": ANNOTATIONS_EXTRACTION_PROMPT.format(
                mistral_text=ocr_filtered["mistral"],
                olm_text=ocr_filtered["olm"],
                paddle_text=ocr_filtered["paddle"],
                headings_json=headings_json,
                structure_json=structure_json,
                pattern_hints_json=pattern_hints_json
            )}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "annotations_extraction",
                "strict": True,
                "schema": AnnotationsOutput.model_json_schema()
            }
        },
        temperature=0.1,
        timeout=300  # 5 minutes - annotation extraction can be slow for complex pages
    )
