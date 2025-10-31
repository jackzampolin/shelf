from typing import List
from pydantic import BaseModel, Field

from .block_correction import BlockCorrection


class CorrectionLLMResponse(BaseModel):
    blocks: List[BlockCorrection] = Field(..., description="Block corrections")
