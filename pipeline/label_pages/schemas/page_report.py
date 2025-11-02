from typing import Optional, Literal
from pydantic import BaseModel, Field

PageRegion = Literal["front_matter", "body", "back_matter"]


class LabelPagesPageReport(BaseModel):
    page_num: int = Field(..., ge=1, description="PDF page number")
    printed_page_number: Optional[str] = Field(None, description="Printed page number on page (e.g., 'ix', '45', None)")
    numbering_style: Optional[Literal["roman", "arabic", "none"]] = Field(None, description="Page numbering style")
    page_region: Optional[PageRegion] = Field(None, description="Book region (front/body/back matter)")
    page_number_extracted: bool = Field(..., description="Was a printed page number found?")
    page_region_classified: bool = Field(..., description="Was page region identified?")
    total_blocks_classified: int = Field(..., ge=0, description="Blocks classified on this page")
    avg_classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Classification quality (low = needs review)")

    has_chapter_heading: bool = Field(..., description="Does this page contain a CHAPTER_HEADING block?")
    has_section_heading: bool = Field(..., description="Does this page contain a SECTION_HEADING block?")
    chapter_heading_text: Optional[str] = Field(None, description="Text of chapter heading if present (first 100 chars)")
