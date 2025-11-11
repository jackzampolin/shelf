from pydantic import BaseModel, Field


class LabelStructurePageReport(BaseModel):
    """Report schema for label-structure output - human-readable summary for CSV."""

    page_num: int = Field(..., ge=1, description="Page number")

    # HEADER (running headers in margins)
    header_present: bool = Field(..., description="Header present?")
    header_text: str = Field(default="", description="Header text if present")
    header_conf: str = Field(..., description="Header confidence (high/medium/low)")
    header_source: str = Field(..., description="Source provider")

    # FOOTER
    footer_present: bool = Field(..., description="Footer present?")
    footer_text: str = Field(default="", description="Footer text if present")
    footer_conf: str = Field(..., description="Footer confidence (high/medium/low)")
    footer_source: str = Field(..., description="Source provider")

    # PAGE NUMBER
    page_num_present: bool = Field(..., description="Page number present?")
    page_num_value: str = Field(default="", description="Page number value if present")
    page_num_location: str = Field(default="", description="Location (header/footer/margin)")
    page_num_conf: str = Field(..., description="Page number confidence (high/medium/low)")
    page_num_source: str = Field(..., description="Source provider")

    # HEADINGS (chapter/section titles in body)
    headings_present: bool = Field(..., description="Headings present?")
    headings_count: int = Field(default=0, description="Number of headings")
    headings_text: str = Field(default="", description="Heading texts (pipe-separated)")
    headings_levels: str = Field(default="", description="Heading levels (pipe-separated)")
    headings_conf: str = Field(..., description="Headings confidence (high/medium/low)")
    headings_source: str = Field(..., description="Source provider")
