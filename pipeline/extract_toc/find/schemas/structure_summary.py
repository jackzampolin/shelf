from typing import Dict, List
from pydantic import BaseModel, Field

from .level_pattern import LevelPattern


class StructureSummary(BaseModel):
    """
    Global structure analysis of ToC across all pages.

    Synthesized by find-toc agent after exploring all ToC pages.
    Provides extract-toc with high-level guidance for consistent level assignment.
    """
    total_levels: int = Field(
        ...,
        ge=1,
        le=3,
        description="Total number of hierarchy levels observed (1, 2, or 3)"
    )
    level_patterns: Dict[int, LevelPattern] = Field(
        ...,
        description="Visual and structural patterns for each level (keys: 1, 2, 3)"
    )
    consistency_notes: List[str] = Field(
        default_factory=list,
        description="Notes about structural consistency or variations across pages"
    )
