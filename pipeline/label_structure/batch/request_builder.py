from infra.llm.models import LLMRequest
from ..schemas.llm_response import StructureExtractionResponse


STRUCTURE_EXTRACTION_PROMPT = """Extract structural metadata from three OCR outputs of the same book page.

<mistral_ocr>
{mistral_text}
</mistral_ocr>

<olm_ocr>
{olm_text}
</olm_ocr>

<paddle_ocr>
{paddle_text}
</paddle_ocr>

## Important: OCR Quality Check

If ANY OCR output is corrupted (repetitive garbage like "I I I I...", random characters, or clearly nonsensical):
- Set ALL observations to `present: false` with `confidence: "low"`
- Use empty strings for text fields
- Skip to response - don't try to extract structure from garbage

## Process in Order (only if OCR outputs are valid)

**1. Headings** (from Mistral only)
- Lines starting with `#`, `##`, `###`, etc.
- Remember heading text for step 2

**2. Headers/Footers** (compare Paddle vs Mistral/Olm)
- First lines in Paddle MISSING from Mistral/Olm = header
- Last lines in Paddle MISSING from Mistral/Olm = footer
- Exclude lines matching heading text from step 1
- If Paddle ≈ Mistral/Olm, no header/footer

**3. Page Numbers** (from header/footer only)
- Look only in header/footer text from step 2
- Patterns: "Page 34", "- 34 -", standalone numbers
- Not from heading text

**Confidence:** high (clear) | medium (somewhat clear) | low (uncertain)"""


def prepare_structure_extraction_request(
    item: int,  # page_num
    storage,  # BookStorage
    **kwargs
) -> LLMRequest:
    page_num = item
    mistral_output = storage.stage("mistral-ocr").load_page(page_num)
    olm_output = storage.stage("olm-ocr").load_page(page_num)
    paddle_output = storage.stage("paddle-ocr").load_page(page_num)

    prompt = STRUCTURE_EXTRACTION_PROMPT.format(
        mistral_text=mistral_output.get("markdown", ""),
        olm_text=olm_output.get("text", ""),
        paddle_text=paddle_output.get("text", "")
    )

    return LLMRequest(
        id=f"page_{page_num:04d}",
        model=kwargs.get("model", "xai/grok-4-fast"),
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "structure_extraction",
                "strict": True,
                "schema": StructureExtractionResponse.model_json_schema()
            }
        },
        temperature=0.1,
        timeout=30,  # 30s request timeout + 30s grace = 60s total
        metadata={
            "page_num": page_num,
        }
    )
