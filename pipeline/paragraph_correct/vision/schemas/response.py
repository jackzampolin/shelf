"""
Dynamic Schema Builder for Correction LLM Responses

Generates page-specific JSON schemas that constrain the LLM response
to match the exact structure of the OCR input (same number of blocks
and paragraphs). This prevents the LLM from adding, removing, or
reorganizing the document structure.
"""

import copy
from typing import Dict, Any

from pipeline.ocr.schemas import OCRPageOutput
from .llm_response import CorrectionLLMResponse


def build_page_specific_schema(ocr_page: OCRPageOutput) -> Dict[str, Any]:
    """
    Generate JSON schema tailored to THIS page's OCR structure.

    Constrains block count and paragraph count per block to match OCR exactly.
    This prevents the LLM from adding/removing blocks or paragraphs.

    Args:
        ocr_page: OCR page output with blocks and paragraphs

    Returns:
        OpenRouter response_format dict with page-specific constraints

    Example:
        ocr_page has 3 blocks with [2, 4, 1] paragraphs
        → Schema enforces exactly 3 blocks with exactly [2, 4, 1] paragraphs
        → LLM cannot add/remove blocks or paragraphs
    """
    # Get base schema from Pydantic model
    base_schema = CorrectionLLMResponse.model_json_schema()
    schema = copy.deepcopy(base_schema)

    # Constrain top-level blocks array to exact count from OCR
    num_blocks = len(ocr_page.blocks)
    schema['properties']['blocks']['minItems'] = num_blocks
    schema['properties']['blocks']['maxItems'] = num_blocks

    # Use prefixItems to constrain paragraph count for each block
    block_items = []
    for block in ocr_page.blocks:
        para_count = len(block.paragraphs)

        # Get the BlockCorrection schema from $defs
        block_schema = copy.deepcopy(schema['$defs']['BlockCorrection'])

        # Constrain this specific block's paragraph array
        block_schema['properties']['paragraphs']['minItems'] = para_count
        block_schema['properties']['paragraphs']['maxItems'] = para_count

        block_items.append(block_schema)

    # Replace items with prefixItems for tuple validation
    schema['properties']['blocks']['prefixItems'] = block_items
    # items: false means no additional items beyond prefixItems
    schema['properties']['blocks']['items'] = False

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "ocr_correction",
            "strict": True,
            "schema": schema
        }
    }
