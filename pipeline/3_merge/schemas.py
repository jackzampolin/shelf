"""
Merge Stage Schemas

Unified page representation combining OCR and Correction data.

Design philosophy:
- Single source of truth for each page
- Preserves spatial information (bounding boxes from OCR)
- Includes semantic information (classifications from Correction)
- Tracks correction provenance (which text came from where)
- Detects paragraph continuation across pages
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class PageDimensions(BaseModel):
    """Page dimensions in pixels."""
    width: int = Field(..., ge=1, description="Page width in pixels")
    height: int = Field(..., ge=1, description="Page height in pixels")


class MergedParagraph(BaseModel):
    """
    Merged paragraph combining OCR and Correction data.

    Contains the final text (corrected if available, otherwise OCR),
    spatial location, and provenance tracking.
    """
    par_num: int = Field(..., ge=1, description="Paragraph number within block")
    text: str = Field(..., min_length=1, description="Final paragraph text (corrected or OCR)")
    bbox: List[int] = Field(..., description="Bounding box [x, y, width, height]")

    # Provenance tracking
    original_confidence: float = Field(..., ge=0.0, le=1.0, description="Original OCR confidence")
    correction_applied: bool = Field(..., description="Whether correction was applied")
    correction_confidence: float = Field(..., ge=0.0, le=1.0, description="Correction confidence (1.0 if no correction)")
    correction_notes: Optional[str] = Field(None, description="Explanation of corrections made")


class MergedBlock(BaseModel):
    """
    Merged block combining OCR spatial structure and Correction classification.

    Preserves Tesseract's spatial block detection while adding semantic
    classification from the correction stage.
    """
    block_num: int = Field(..., ge=1, description="Block number (from OCR)")
    classification: str = Field(..., description="Block content type (from Correction)")
    classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence")
    bbox: List[int] = Field(..., description="Block bounding box [x, y, width, height]")

    paragraphs: List[MergedParagraph] = Field(..., description="Paragraphs in this block")


class ContinuationInfo(BaseModel):
    """
    Information about paragraph continuation across pages.

    Detected heuristically based on:
    - Sentence completion (does last paragraph end with punctuation?)
    - Hyphenation (does last word end with hyphen?)
    - Case (does next page start with lowercase?)
    """
    continues_from_previous: bool = Field(..., description="Page starts mid-paragraph from previous page")
    continues_to_next: bool = Field(..., description="Page ends mid-paragraph continuing to next page")


class MergeMetadata(BaseModel):
    """Metadata tracking the merge process."""
    ocr_timestamp: str = Field(..., description="When OCR was performed")
    correction_timestamp: str = Field(..., description="When correction was performed")
    correction_model: str = Field(..., description="Model used for correction")
    merge_timestamp: str = Field(..., description="When merge was performed")
    total_blocks: int = Field(..., ge=0, description="Total blocks on page")
    total_corrections_applied: int = Field(..., ge=0, description="Count of paragraphs with corrections")


class MergedPageOutput(BaseModel):
    """
    Complete merged page representation.

    This is the schema saved to processed/page_XXXX.json files.
    Serves as input to structure detection and chunking stages.
    """
    page_number: int = Field(..., ge=1, description="Page number in book")
    page_dimensions: PageDimensions = Field(..., description="Page dimensions")

    blocks: List[MergedBlock] = Field(..., description="Merged blocks with full text and classifications")
    continuation: ContinuationInfo = Field(..., description="Paragraph continuation information")

    metadata: MergeMetadata = Field(..., description="Processing metadata")

    def get_full_text(self) -> str:
        """Get all text from all blocks concatenated."""
        return "\n\n".join(
            "\n\n".join(p.text for p in block.paragraphs)
            for block in self.blocks
        )

    def get_corrected_paragraphs(self) -> List[MergedParagraph]:
        """Get all paragraphs that had corrections applied."""
        corrected = []
        for block in self.blocks:
            corrected.extend([p for p in block.paragraphs if p.correction_applied])
        return corrected

    def get_body_blocks(self) -> List[MergedBlock]:
        """Get blocks classified as BODY text."""
        return [b for b in self.blocks if b.classification == "BODY"]

    def get_blocks_by_type(self, block_type: str) -> List[MergedBlock]:
        """Get all blocks of a specific classification type."""
        return [b for b in self.blocks if b.classification == block_type]
