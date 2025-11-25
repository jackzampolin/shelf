from infra.llm.models import LLMRequest
from .prompt import BLEND_SYSTEM_PROMPT, BLEND_USER_PROMPT


def prepare_blend_request(item: int, storage) -> LLMRequest:
    ocr_stage = storage.stage("ocr-pages")

    try:
        mistral_data = ocr_stage.load_page(item, subdir="mistral")
        mistral_text = mistral_data.get("markdown", "")
    except FileNotFoundError:
        mistral_text = ""
    except Exception as e:
        raise ValueError(f"Failed to load Mistral OCR for page {item:04d}: {type(e).__name__}: {e}")

    try:
        olm_data = ocr_stage.load_page(item, subdir="olm")
        olm_text = olm_data.get("text", "")
    except FileNotFoundError:
        olm_text = ""
    except Exception as e:
        raise ValueError(f"Failed to load OLM OCR for page {item:04d}: {type(e).__name__}: {e}")

    try:
        paddle_data = ocr_stage.load_page(item, subdir="paddle")
        paddle_text = paddle_data.get("text", "")
    except FileNotFoundError:
        paddle_text = ""
    except Exception as e:
        raise ValueError(f"Failed to load Paddle OCR for page {item:04d}: {type(e).__name__}: {e}")

    if not mistral_text and not olm_text and not paddle_text:
        raise ValueError(f"No OCR data available for page {item:04d} - all three OCR sources are empty")

    source_image = storage.source().load_page_image(item, downsample=True, max_payload_kb=800)

    return LLMRequest(
        id=f"page_{item:04d}",
        messages=[
            {"role": "system", "content": BLEND_SYSTEM_PROMPT},
            {"role": "user", "content": BLEND_USER_PROMPT.format(
                mistral_text=mistral_text,
                olm_text=olm_text,
                paddle_text=paddle_text,
            )},
        ],
        images=[source_image],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "blended_markdown",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "markdown": {
                            "type": "string",
                            "description": "The synthesized markdown transcription"
                        }
                    },
                    "required": ["markdown"],
                    "additionalProperties": False
                }
            }
        },
        temperature=0.1,
        timeout=180,
    )
