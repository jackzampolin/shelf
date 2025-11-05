from typing import Optional
from pydantic import BaseModel, Field


class LabelPagesPageReport(BaseModel):
    """Simplified report schema for label-pages output - human-readable summary."""

    page_num: int = Field(..., ge=1, description="Scan page number")

    # BOUNDARY DETECTION (primary signal)
    is_boundary: bool = Field(..., description="Is this a structural boundary?")
    boundary_conf: float = Field(..., ge=0.0, le=1.0, description="Boundary confidence")

    # HEADING INFO (if boundary detected)
    heading_text: Optional[str] = Field(None, description="Extracted heading text")
    heading_type: Optional[str] = Field(None, description="Suggested type (chapter/part/section/etc)")
    type_conf: float = Field(0.0, ge=0.0, le=1.0, description="Type confidence")

    # VISUAL SIGNALS
    whitespace: str = Field(..., description="Whitespace amount (minimal/moderate/extensive)")
    heading_size: str = Field(..., description="Heading size (none/small/medium/large/very_large)")
    heading_visible: bool = Field(..., description="Is heading visible?")

    # TEXTUAL SIGNALS
    starts_with_heading: bool = Field(..., description="OCR starts with heading?")
    appears_to_continue: bool = Field(..., description="Text continues from previous page?")
    first_line: str = Field(..., description="First line of OCR text (preview)")
