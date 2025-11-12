from infra.llm.models import LLMRequest
from ..schemas.llm_response import StructureExtractionResponse
from .prompt import STRUCTURE_EXTRACTION_PROMPT

def prepare_structure_extraction_request(
    item: int,
    storage,
) -> LLMRequest:
    return LLMRequest(
        id=f"page_{item:04d}",
        messages=[{
            "role": "user", 
            "content": STRUCTURE_EXTRACTION_PROMPT.format(
                mistral_text=storage.stage("mistral-ocr").load_page(item).get("markdown", ""),
                olm_text=storage.stage("olm-ocr").load_page(item).get("text", ""),
                paddle_text=storage.stage("paddle-ocr").load_page(item).get("text", "")
            )}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "structure_extraction",
                "strict": True,
                "schema": StructureExtractionResponse.model_json_schema()
            }
        },
        temperature=0.1,
        timeout=30
    )
