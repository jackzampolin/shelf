"""
LLM Response Schema

The structured response we request from the vision LLM.
This schema is page-specific (constrained to match OCR block count).
"""

from typing import List, Optional, Literal
from enum import Enum
from pydantic import BaseModel, Field


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
    """Classification labels for a single block."""

    block_num: int = Field(..., ge=1, description="Block number (matches OCR)")
    classification: BlockType = Field(..., description="Classified content type")
    classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in classification")


class LabelLLMResponse(BaseModel):
    """
    Structured LLM response for label stage.

    This schema is constrained at runtime to match the OCR block count
    using minItems/maxItems on the blocks array.
    """

    # Book page number extraction (from vision analysis)
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

    # Classified blocks (constrained to match OCR block count at runtime)
    blocks: List[BlockClassification] = Field(..., description="Block classifications")
