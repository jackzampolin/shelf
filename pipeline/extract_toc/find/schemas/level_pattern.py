from typing import Optional
from pydantic import BaseModel, Field


class LevelPattern(BaseModel):
    """
    Visual and structural pattern for a specific ToC hierarchy level.

    Captured during find-toc page exploration to guide extract-toc phase.
    """
    visual: str = Field(
        ...,
        description="Visual characteristics: indentation distance, styling (bold, larger font, etc.)"
    )
    numbering: Optional[str] = Field(
        None,
        description="Numbering scheme if present: Roman numerals (I, II), Arabic (1, 2, 3), decimal (1.1, 2.3), letters (A, B)"
    )
    has_page_numbers: bool = Field(
        ...,
        description="Whether entries at this level have page number references"
    )
    semantic_type: Optional[str] = Field(
        None,
        description="Common semantic type if detectable: 'volume', 'book', 'part', 'unit', 'chapter', 'section', 'subsection', 'act', 'scene', 'appendix'"
    )
