"""
Dynamic Schema Builder for Label LLM Responses

Generates page-specific JSON schemas that constrain the LLM response
to match the exact number of blocks from OCR. This prevents the LLM
from adding or removing blocks.
"""

import copy
import json
from typing import Dict, Any

from pipeline.ocr.schemas import OCRPageOutput
from .llm_response import LabelLLMResponse


def build_page_specific_schema(ocr_page: OCRPageOutput) -> Dict[str, Any]:
    """
    Generate JSON schema tailored to THIS page's OCR structure.

    Constrains block count to match OCR exactly.
    This prevents the LLM from adding/removing blocks.

    Args:
        ocr_page: OCR page output with blocks

    Returns:
        OpenRouter response_format dict with page-specific constraints

    Example:
        ocr_page has 5 blocks
        → Schema enforces exactly 5 blocks
        → LLM cannot add/remove blocks
    """
    # Get base schema from Pydantic model
    base_schema = LabelLLMResponse.model_json_schema()
    schema = copy.deepcopy(base_schema)

    # Constrain top-level blocks array to exact count from OCR
    num_blocks = len(ocr_page.blocks)
    schema['properties']['blocks']['minItems'] = num_blocks
    schema['properties']['blocks']['maxItems'] = num_blocks

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "page_labeling",
            "strict": True,
            "schema": schema
        }
    }
