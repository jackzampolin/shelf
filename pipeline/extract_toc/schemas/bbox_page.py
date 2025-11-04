from typing import List, Optional
from pydantic import BaseModel, Field

from pipeline.ocr.schemas.bounding_box import BoundingBox
from .toc_entry import ToCEntry


class BboxPageExtraction(BaseModel):
    """
    Phase 2: Bounding boxes extracted by vision model for a single ToC page.

    Vision model identifies visual elements (entries, page numbers) and places
    boxes around them. No classification needed - position determines purpose.
    """
    page_num: int = Field(..., ge=1, description="Page number in the book")
    bboxes: List[BoundingBox] = Field(..., description="All bounding boxes on this page (unordered)")
    extraction_confidence: float = Field(..., ge=0.0, le=1.0, description="Vision model's confidence")
    notes: str = Field("", description="Vision model's notes about this page's structure")


class BboxPageVerified(BaseModel):
    """
    Phase 3: Self-verified bounding boxes after vision model checks its own work.

    Vision model reviews extracted boxes and confirms:
    - All ToC elements have boxes
    - Each box contains one structural element
    - No missing or duplicate boxes
    """
    page_num: int = Field(..., ge=1, description="Page number in the book")
    bboxes: List[BoundingBox] = Field(..., description="Verified bounding boxes (ordered top to bottom)")
    verification_passed: bool = Field(..., description="Did self-verification pass?")
    corrections_made: int = Field(0, ge=0, description="Number of boxes added/removed/adjusted")
    verification_notes: str = Field("", description="Notes about verification process")


class BboxOCRText(BaseModel):
    """
    Single OCR result for one bounding box.
    """
    bbox: BoundingBox = Field(..., description="The bounding box coordinates")
    text: str = Field(..., description="OCR'd text from Tesseract")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Tesseract's confidence score")


class BboxPageOCR(BaseModel):
    """
    Phase 4: OCR results for all bounding boxes on a ToC page.

    Each bbox has been processed by Tesseract to extract text.
    Boxes are ordered top-to-bottom (by y-coordinate).
    """
    page_num: int = Field(..., ge=1, description="Page number in the book")
    ocr_results: List[BboxOCRText] = Field(..., description="OCR text for each bbox (ordered by Y position)")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Average Tesseract confidence")
    tesseract_version: str = Field(..., description="Tesseract version used")


class TocPageAssembly(BaseModel):
    """
    Phase 5: Assembled ToC entries from a single page.

    LLM interprets OCR'd text boxes and their positions to build ToC entries.
    Uses Y-position for vertical grouping (one entry per row) and X-position
    for horizontal classification (left=title, right=page number).
    """
    page_num: int = Field(..., ge=1, description="Page number in the book")
    entries: List[ToCEntry] = Field(..., description="ToC entries assembled from this page")
    assembly_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in assembly quality")
    notes: str = Field("", description="Assembly notes, especially about continuations or ambiguities")
    prior_context_used: bool = Field(False, description="Did this page use prior page context?")
