import copy
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from pipeline.ocr.schemas import OCRPageOutput


class ParagraphCorrection(BaseModel):
    par_num: int = Field(..., ge=1, description="Paragraph number within block (matches OCR)")
    text: Optional[str] = Field(None, description="Full corrected paragraph text (omit if no errors found)")
    notes: Optional[str] = Field(None, description="Brief explanation of changes made (e.g., 'Fixed hyphenation, 2 OCR errors')")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in text quality")


class BlockCorrection(BaseModel):
    block_num: int = Field(..., ge=1, description="Block number (matches OCR)")
    paragraphs: List[ParagraphCorrection] = Field(..., description="Paragraph-level corrections")


class CorrectionLLMResponse(BaseModel):
    blocks: List[BlockCorrection] = Field(..., description="Block corrections")


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
