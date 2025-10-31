import copy
from typing import Dict, Any

from pipeline.ocr.schemas import OCRPageOutput
from .llm_response import CorrectionLLMResponse


def build_page_specific_schema(ocr_page: OCRPageOutput) -> Dict[str, Any]:
    base_schema = CorrectionLLMResponse.model_json_schema()
    schema = copy.deepcopy(base_schema)

    num_blocks = len(ocr_page.blocks)
    schema['properties']['blocks']['minItems'] = num_blocks
    schema['properties']['blocks']['maxItems'] = num_blocks

    block_items = []
    for block in ocr_page.blocks:
        para_count = len(block.paragraphs)

        block_schema = copy.deepcopy(schema['$defs']['BlockCorrection'])

        block_schema['properties']['paragraphs']['minItems'] = para_count
        block_schema['properties']['paragraphs']['maxItems'] = para_count

        block_items.append(block_schema)

    schema['properties']['blocks']['prefixItems'] = block_items
    schema['properties']['blocks']['items'] = False

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "ocr_correction",
            "strict": True,
            "schema": schema
        }
    }
