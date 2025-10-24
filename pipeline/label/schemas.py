"""
Label Stage Schemas

Vision-based page number extraction and block classification.
Text correction is handled in Stage 2.
"""

from typing import List, Optional, Literal
from enum import Enum
from pydantic import BaseModel, Field
from infra.pipeline.schemas import LLMPageMetrics


class BlockType(str, Enum):
    """Classification types for book content blocks."""

    # Front matter
    TITLE_PAGE = "TITLE_PAGE"
    COPYRIGHT = "COPYRIGHT"
    DEDICATION = "DEDICATION"
    TABLE_OF_CONTENTS = "TABLE_OF_CONTENTS"
    PREFACE = "PREFACE"
    FOREWORD = "FOREWORD"
    INTRODUCTION = "INTRODUCTION"

    # Main content
    CHAPTER_HEADING = "CHAPTER_HEADING"
    SECTION_HEADING = "SECTION_HEADING"
    BODY = "BODY"
    QUOTE = "QUOTE"
    EPIGRAPH = "EPIGRAPH"

    # Notes and references
    FOOTNOTE = "FOOTNOTE"
    ENDNOTES = "ENDNOTES"
    BIBLIOGRAPHY = "BIBLIOGRAPHY"
    REFERENCES = "REFERENCES"
    INDEX = "INDEX"

    # Back matter
    EPILOGUE = "EPILOGUE"
    APPENDIX = "APPENDIX"
    GLOSSARY = "GLOSSARY"
    ACKNOWLEDGMENTS = "ACKNOWLEDGMENTS"

    # Metadata/navigation
    HEADER = "HEADER"
    FOOTER = "FOOTER"
    PAGE_NUMBER = "PAGE_NUMBER"

    # Special
    ILLUSTRATION_CAPTION = "ILLUSTRATION_CAPTION"
    CAPTION = "CAPTION"  # Generic caption (maps to ILLUSTRATION_CAPTION)
    TABLE = "TABLE"
    MAP_LABEL = "MAP_LABEL"  # Geographic/map labels and annotations
    DIAGRAM_LABEL = "DIAGRAM_LABEL"  # Timeline, chart, diagram labels
    PHOTO_CREDIT = "PHOTO_CREDIT"  # Photo/image attribution text
    OCR_ARTIFACT = "OCR_ARTIFACT"  # Garbled/nonsense text from OCR errors
    OTHER = "OTHER"  # Catch-all (use sparingly)


class PageRegion(str, Enum):
    """Page region classification based on position in book."""
    FRONT_MATTER = "front_matter"  # Before main body (ToC, preface, etc.)
    BODY = "body"                   # Main content chapters
    BACK_MATTER = "back_matter"     # After main body (index, bibliography, etc.)
    TOC_AREA = "toc_area"           # Table of Contents region
    UNCERTAIN = "uncertain"          # Ambiguous or insufficient context


class BlockClassification(BaseModel):
    """Classification labels for a single block (no text correction)."""

    block_num: int = Field(..., ge=1, description="Block number (matches OCR)")
    classification: BlockType = Field(..., description="Classified content type")
    classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in classification")


class LabelPageOutput(BaseModel):
    """Output from vision-based page number extraction and block classification."""

    # Page identification
    page_number: int = Field(..., ge=1)

    # Book page number extraction (from vision analysis)
    # Note: This is the number PRINTED on the page image, NOT the pdf-page file number
    printed_page_number: Optional[str] = Field(
        None,
        description="Book-page number as printed on the image (e.g., 'ix', '45', None if unnumbered)"
    )
    numbering_style: Optional[Literal["roman", "arabic", "none"]] = Field(
        None,
        description="Style of book-page numbering detected"
    )
    page_number_location: Optional[Literal["header", "footer", "none"]] = Field(
        None,
        description="Where the book-page number was found on the image"
    )
    page_number_confidence: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in book-page number extraction (1.0 if no number found)"
    )

    # Page region classification (from position in book)
    page_region: Optional[PageRegion] = Field(
        None,
        description="Classified region of book (front/body/back matter, ToC)"
    )
    page_region_confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Confidence in page region classification"
    )

    # Classified blocks (no text correction)
    blocks: List[BlockClassification] = Field(..., description="Block classifications")

    # Processing metadata
    model_used: str = Field(..., description="Model used for labeling (e.g., 'gpt-4o')")
    processing_cost: float = Field(..., ge=0.0, description="Cost of this page in USD")
    timestamp: str = Field(..., description="ISO timestamp of processing")

    # Summary statistics
    total_blocks: int = Field(..., ge=0, description="Total number of blocks classified")
    avg_classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Average block classification confidence")


# ============================================================================
# Checkpoint Metrics Schema
# ============================================================================


class LabelPageMetrics(LLMPageMetrics):
    """
    Checkpoint metrics for Label stage.

    Extends LLMPageMetrics with label-specific quality metrics.
    Tracks both LLM performance (tokens, timing, cost) and labeling
    quality (classification confidence, page number extraction success).

    Includes book structure fields for report generation.
    """
    # Label-specific metrics
    total_blocks_classified: int = Field(..., ge=0, description="Number of blocks classified")
    avg_classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Average block classification confidence")
    page_number_extracted: bool = Field(..., description="Whether a printed page number was found")
    page_region_classified: bool = Field(..., description="Whether page region was classified (front/body/back matter)")

    # Book structure fields (for report generation)
    printed_page_number: Optional[str] = Field(None, description="Printed page number on page")
    numbering_style: Optional[Literal["roman", "arabic", "none"]] = Field(None, description="Page numbering style")
    page_region: Optional[PageRegion] = Field(None, description="Book region classification")

    # Chapter/section structure (for build-structure stage)
    has_chapter_heading: bool = Field(False, description="Does this page contain a CHAPTER_HEADING block?")
    has_section_heading: bool = Field(False, description="Does this page contain a SECTION_HEADING block?")
    chapter_heading_text: Optional[str] = Field(None, description="Text of chapter heading if present (first 100 chars)")


# ============================================================================
# Report Schema (Quality metrics only)
# ============================================================================


class LabelPageReport(BaseModel):
    """
    Quality-focused report for Label stage.

    Shows book structure and identifies classification issues:
    - Page numbering progression (gaps, style changes)
    - Region transitions (front → body → back matter)
    - Classification quality (low confidence, missing extractions)
    - Chapter/section boundaries (for build-structure stage)
    """
    page_num: int = Field(..., ge=1, description="PDF page number")
    printed_page_number: Optional[str] = Field(None, description="Printed page number on page (e.g., 'ix', '45', None)")
    numbering_style: Optional[Literal["roman", "arabic", "none"]] = Field(None, description="Page numbering style")
    page_region: Optional[PageRegion] = Field(None, description="Book region (front/body/back matter)")
    page_number_extracted: bool = Field(..., description="Was a printed page number found?")
    page_region_classified: bool = Field(..., description="Was page region identified?")
    total_blocks_classified: int = Field(..., ge=0, description="Blocks classified on this page")
    avg_classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Classification quality (low = needs review)")

    # Chapter/section structure (for build-structure stage)
    has_chapter_heading: bool = Field(..., description="Does this page contain a CHAPTER_HEADING block?")
    has_section_heading: bool = Field(..., description="Does this page contain a SECTION_HEADING block?")
    chapter_heading_text: Optional[str] = Field(None, description="Text of chapter heading if present (first 100 chars)")
