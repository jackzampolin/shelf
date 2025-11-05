from typing import Optional
from pydantic import BaseModel, Field


class LabelPagesPageReport(BaseModel):
    """Report schema for label-pages output - human-readable summary."""

    page_num: int = Field(..., ge=1, description="Scan page number")

    # Page number metadata
    printed_page_number: Optional[str] = Field(None, description="Printed page number ('ix', '45', None)")
    numbering_style: str = Field(..., description="Numbering style (roman/arabic/none)")
    page_number_location: str = Field(..., description="Location (header/footer/none)")

    # Page region
    page_region: str = Field(..., description="Book region (front_matter/body/back_matter)")

    # Structural boundary
    is_boundary: bool = Field(..., description="Is this a structural boundary?")
    boundary_type: Optional[str] = Field(None, description="Suggested type (part/chapter/section)")
    whitespace: str = Field(..., description="Whitespace amount (minimal/moderate/extensive)")
    heading_size: str = Field(..., description="Heading size (none/small/medium/large/very_large)")

    # Content flags
    has_toc: bool = Field(..., description="Contains table of contents?")

    # Confidence indicators
    page_num_conf: float = Field(..., ge=0.0, le=1.0, description="Page number confidence")
    region_conf: float = Field(..., ge=0.0, le=1.0, description="Region confidence")
    boundary_conf: float = Field(..., ge=0.0, le=1.0, description="Boundary confidence")
