from pydantic import BaseModel, Field


class LinkTocReportEntry(BaseModel):
    """CSV report row for link-toc output."""

    toc_index: int = Field(..., ge=0, description="ToC entry index")
    toc_title: str = Field(..., description="ToC entry title")
    printed_page: str = Field(..., description="Printed page number from ToC (or 'N/A')")
    scan_page: str = Field(..., description="Scan page number where found (or 'NOT_FOUND')")
    reasoning: str = Field(..., description="Agent reasoning (truncated for CSV)")
