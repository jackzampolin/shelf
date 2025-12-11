"""Gap investigator agent for page coverage validation."""

from .investigator_tools import GapInvestigatorTools
from .prompts import INVESTIGATOR_SYSTEM_PROMPT, build_investigator_user_prompt

__all__ = [
    "GapInvestigatorTools",
    "INVESTIGATOR_SYSTEM_PROMPT",
    "build_investigator_user_prompt",
]
