from typing import List
from pydantic import BaseModel, Field

from .block_classification import BlockClassification


class LabelLLMResponse(BaseModel):
    """
    Stage 2 LLM Response: Block-level classifications only.

    Page-level metadata (page numbers, page regions, structural boundaries)
    comes from Stage 1's 3-image context analysis. Stage 2 focuses solely on
    classifying OCR blocks using Stage 1 context as guidance.

    This separation ensures:
    - Clear responsibility: Stage 1 = page-level, Stage 2 = block-level
    - Single source of truth: No conflicting page-level data
    - Cost efficiency: Stage 2 doesn't re-extract what Stage 1 already found
    """
    blocks: List[BlockClassification] = Field(
        ...,
        description="Block-level classifications for all OCR blocks on this page"
    )
