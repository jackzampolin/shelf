import json
from infra.llm.models import LLMRequest
from infra.ocr import filter_ocr_quality
from ..schemas.structure import StructuralMetadataOutput
from .prompt import STRUCTURAL_METADATA_PROMPT


def prepare_structural_metadata_request(
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

    headings_json = json.dumps(mechanical_output.get("headings", []), indent=2)
    pattern_hints_json = json.dumps(mechanical_output.get("pattern_hints", {}), indent=2)

    # Load OCR texts with error handling
    ocr_stage = storage.stage("ocr-pages")

    try:
        mistral_text = ocr_stage.load_page(item, subdir="mistral").get("markdown", "")
    except FileNotFoundError:
        mistral_text = ""
    except Exception as e:
        raise ValueError(f"Failed to load Mistral OCR for page {item:04d}: {type(e).__name__}: {e}")

    try:
        olm_text = ocr_stage.load_page(item, subdir="olm").get("text", "")
    except FileNotFoundError:
        olm_text = ""
    except Exception as e:
        raise ValueError(f"Failed to load OLM OCR for page {item:04d}: {type(e).__name__}: {e}")

    try:
        paddle_text = ocr_stage.load_page(item, subdir="paddle").get("text", "")
    except FileNotFoundError:
        paddle_text = ""
    except Exception as e:
        raise ValueError(f"Failed to load Paddle OCR for page {item:04d}: {type(e).__name__}: {e}")

    if not mistral_text and not olm_text and not paddle_text:
        raise ValueError(f"No OCR data available for page {item:04d} - all three OCR sources are empty")

    # Filter out low-quality OCR output (e.g., PADDLE hallucinations on TOC/index pages)
    ocr_filtered = filter_ocr_quality(mistral_text, olm_text, paddle_text)

    return LLMRequest(
        id=f"page_{item:04d}",
        messages=[{
            "role": "user",
            "content": STRUCTURAL_METADATA_PROMPT.format(
                mistral_text=ocr_filtered["mistral"],
                olm_text=ocr_filtered["olm"],
                paddle_text=ocr_filtered["paddle"],
                headings_json=headings_json,
                pattern_hints_json=pattern_hints_json
            )}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "structural_metadata",
                "strict": True,
                "schema": StructuralMetadataOutput.model_json_schema()
            }
        },
        temperature=0.1,
        timeout=300  # 5 minutes - structure extraction can be slow for complex pages
    )
