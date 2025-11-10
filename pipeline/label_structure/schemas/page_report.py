from pydantic import BaseModel, Field


class LabelPagesPageReport(BaseModel):
    """Report schema for label-pages output - human-readable summary for CSV."""

    scan_page_number: int = Field(..., ge=1, description="Scan page number")

    # WHITESPACE
    whitespace_zones: str = Field(..., description="Whitespace zones (e.g., 'top,middle' or 'none')")
    whitespace_conf: float = Field(..., ge=0.0, le=1.0, description="Whitespace confidence")

    # TEXT CONTINUATION
    continues_from_prev: bool = Field(..., description="Text continues from previous page?")
    continues_to_next: bool = Field(..., description="Text continues to next page?")
    continuation_conf: float = Field(..., ge=0.0, le=1.0, description="Continuation confidence")

    # HEADING (chapter/section titles in body)
    heading_exists: bool = Field(..., description="Heading exists?")
    heading_text: str = Field(default="", description="Heading text if present")
    heading_position: str = Field(default="", description="Heading position (top/middle/bottom)")
    heading_conf: float = Field(..., ge=0.0, le=1.0, description="Heading confidence")

    # HEADER (running headers in margins)
    header_exists: bool = Field(..., description="Header exists?")
    header_text: str = Field(default="", description="Header text if present")
    header_conf: float = Field(..., ge=0.0, le=1.0, description="Header confidence")

    # FOOTER
    footer_exists: bool = Field(..., description="Footer exists?")
    footer_text: str = Field(default="", description="Footer text if present")
    footer_position: str = Field(default="", description="Footer position (left/center/right)")
    footer_conf: float = Field(..., ge=0.0, le=1.0, description="Footer confidence")

    # ORNAMENTAL BREAK
    ornamental_break: bool = Field(..., description="Ornamental break exists?")
    ornamental_break_position: str = Field(default="", description="Break position (top/middle/bottom)")
    ornamental_break_conf: float = Field(..., ge=0.0, le=1.0, description="Ornamental break confidence")

    # FOOTNOTES
    footnotes_exist: bool = Field(..., description="Footnotes exist?")
    footnotes_conf: float = Field(..., ge=0.0, le=1.0, description="Footnotes confidence")

    # PAGE NUMBER
    page_num_exists: bool = Field(..., description="Page number exists?")
    page_num_value: str = Field(default="", description="Page number value")
    page_num_position: str = Field(default="", description="Page number position")
    page_num_conf: float = Field(..., ge=0.0, le=1.0, description="Page number confidence")
