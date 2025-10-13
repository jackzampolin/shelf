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


class ParagraphCorrection(BaseModel):
    """Correction information for a single paragraph."""

    par_num: int = Field(..., ge=1, description="Paragraph number within block (matches OCR)")

    # Only present if corrections were made - outputs FULL corrected paragraph text
    text: Optional[str] = Field(None, description="Full corrected paragraph text (omit if no errors found)")
    notes: Optional[str] = Field(None, description="Brief explanation of changes made (e.g., 'Fixed hyphenation, 2 OCR errors')")

    # Confidence in the text quality (1.0 if no changes needed)
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in text quality")


class BlockCorrection(BaseModel):
    """Corrections for a single block (no classification)."""

    block_num: int = Field(..., ge=1, description="Block number (matches OCR)")

    paragraphs: List[ParagraphCorrection] = Field(..., description="Paragraph-level corrections")


class CorrectionPageOutput(BaseModel):
    """Output from vision-based correction of a single page."""

    # Page identification
    page_number: int = Field(..., ge=1)

    # Corrected blocks (no classification or page number extraction)
    blocks: List[BlockCorrection] = Field(..., description="Block corrections")

    # Processing metadata
    model_used: str = Field(..., description="Model used for correction (e.g., 'gpt-4o')")
    processing_cost: float = Field(..., ge=0.0, description="Cost of this page in USD")
    timestamp: str = Field(..., description="ISO timestamp of processing")

    # Summary statistics
    total_blocks: int = Field(..., ge=0, description="Total number of blocks corrected")
    total_corrections: int = Field(..., ge=0, description="Total number of paragraphs corrected")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Average text confidence")
