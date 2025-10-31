"""
Vision LLM Module for Paragraph Correction

Handles all vision-based OCR correction logic:
- Prompts (system and user)
- Request preparation (images, schemas, prompts)
- Dynamic schema generation (per-page constraints)
"""

from .prompts import SYSTEM_PROMPT, build_user_prompt
from .caller import prepare_correction_request
from .schemas import build_page_specific_schema

__all__ = [
    "SYSTEM_PROMPT",
    "build_user_prompt",
    "prepare_correction_request",
    "build_page_specific_schema",
]
