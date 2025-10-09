"""
Correction Stage Schemas

Vision-based OCR correction with block classification.
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
    APPENDIX = "APPENDIX"
    GLOSSARY = "GLOSSARY"
    ACKNOWLEDGMENTS = "ACKNOWLEDGMENTS"

    # Metadata/navigation
    HEADER = "HEADER"
    FOOTER = "FOOTER"
    PAGE_NUMBER = "PAGE_NUMBER"

    # Special
    ILLUSTRATION_CAPTION = "ILLUSTRATION_CAPTION"
    TABLE = "TABLE"
    OTHER = "OTHER"  # Catch-all


class TextFix(BaseModel):
    """Details about a specific text correction."""

    original: str = Field(..., description="Original incorrect text")
    corrected: str = Field(..., description="Corrected text")
    reason: str = Field(..., description="Reason for correction (e.g., 'OCR artifact', 'hyphenation')")


class ParagraphCorrection(BaseModel):
    """Correction information for a single paragraph."""

    par_num: int = Field(..., ge=1, description="Paragraph number within block (matches OCR)")

    # Only present if corrections were made
    corrected_text: Optional[str] = Field(None, description="Corrected text (omit if no errors found)")
    corrections: Optional[List[TextFix]] = Field(None, description="List of specific fixes made")

    # Confidence in the correction (1.0 if no changes needed)
    correction_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in correction quality")


class BlockClassification(BaseModel):
    """Classification and corrections for a single block."""

    block_num: int = Field(..., ge=1, description="Block number (matches OCR)")
    classification: BlockType = Field(..., description="Classified content type")
    classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in classification")

    paragraphs: List[ParagraphCorrection] = Field(..., description="Paragraph-level corrections")


class CorrectionPageOutput(BaseModel):
    """Output from vision-based correction of a single page."""

    # Page identification
    page_number: int = Field(..., ge=1)

    # Classified and corrected blocks
    blocks: List[BlockClassification] = Field(..., description="Block classifications and corrections")

    # Processing metadata
    model_used: str = Field(..., description="Model used for correction (e.g., 'gpt-4o')")
    processing_cost: float = Field(..., ge=0.0, description="Cost of this page in USD")
    timestamp: str = Field(..., description="ISO timestamp of processing")

    # Summary statistics
    total_blocks: int = Field(..., ge=0, description="Total number of blocks classified")
    total_corrections: int = Field(..., ge=0, description="Total number of corrections made")
    avg_classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Average classification confidence")
    avg_correction_confidence: float = Field(..., ge=0.0, le=1.0, description="Average correction confidence")
