"""
Correction Stage Schemas

Vision-based OCR correction with block classification.
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


class CorrectionLLMResponse(BaseModel):
    """
    LLM response structure for correction stage.

    This is what the LLM returns. The stage adds metadata to create CorrectionPageOutput.
    Use this model to generate the JSON schema for response_format.
    """
    blocks: List[BlockCorrection] = Field(..., description="Block corrections")


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


# ============================================================================
# Checkpoint Metrics Schema
# ============================================================================


class CorrectionPageMetrics(LLMPageMetrics):
    """
    Checkpoint metrics for Correction stage.

    Extends LLMPageMetrics with correction-specific quality metrics.
    Tracks both LLM performance (tokens, timing, cost) and correction
    quality (how many corrections made, confidence).
    """
    # Correction-specific metrics
    total_corrections: int = Field(..., ge=0, description="Number of paragraphs with corrections")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Average text confidence after correction")

    # Similarity metrics (OCR vs corrected text)
    text_similarity_ratio: float = Field(..., ge=0.0, le=1.0, description="Text similarity between OCR and corrected (1.0 = identical)")
    characters_changed: int = Field(..., ge=0, description="Number of characters modified from OCR")


# ============================================================================
# Report Schema (Quality metrics only)
# ============================================================================


class CorrectionPageReport(BaseModel):
    """
    Quality-focused report for Correction stage.

    Helps identify pages with correction issues:
    - Over-correction (low similarity, many changes)
    - Quality problems (low confidence after correction)
    - Pages needing review (high edit distance)
    """
    page_num: int = Field(..., ge=1, description="Page number")
    total_corrections: int = Field(..., ge=0, description="Paragraphs corrected")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Quality after correction (low = needs review)")
    text_similarity_ratio: float = Field(..., ge=0.0, le=1.0, description="Similarity to OCR (low = major changes)")
    characters_changed: int = Field(..., ge=0, description="Edit magnitude (high = significant rewrites)")
