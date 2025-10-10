"""
Structure Detection Schemas

Book structure extracted from ToC, labels, and LLM validation.

Design philosophy (ToC-first approach):
- ToC is ground truth for chapter titles and book page numbers
- Match ToC entries to CHAPTER_HEADING labels to build PDF ↔ Book page mapping
- Cross-validate with header text for confidence
- LLM validates ALL boundaries liberally (text LLM is cheap)
- Preserve full provenance: how each boundary was detected

Implementation strategy:
- Build schemas iteratively from observed data (test-book-driven)
- Each substage writes intermediate JSON for debugging
- Deterministic stages write checkpoints for resume capability
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# ==============================================================================
# Substage 4a: ToC Parsing Schemas
# ==============================================================================

class TocEntry(BaseModel):
    """
    Single entry from Table of Contents.

    Extracted from TABLE_OF_CONTENTS labeled pages using LLM parsing.
    Preserves hierarchical structure (Parts vs Chapters vs Sections).
    """
    title: str = Field(..., min_length=1, description="Chapter/section title from ToC")
    level: int = Field(..., ge=0, le=3, description="Hierarchy level (0=Part, 1=Chapter, 2=Section, 3=Subsection)")
    entry_type: Literal["part_heading", "chapter", "section", "subsection", "other"] = Field(
        ..., description="Type of ToC entry"
    )

    # Book page number (as printed in book, may be roman/arabic/none)
    book_page: Optional[str] = Field(None, description="Page number as shown in ToC (e.g., 'ix', '45', None)")
    numbering_style: Optional[Literal["roman", "arabic", "none"]] = Field(
        None, description="Style of page numbering"
    )

    # Provenance
    raw_text: str = Field(..., description="Original text from ToC as parsed")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Parsing confidence from LLM")


class TocOutput(BaseModel):
    """
    Complete Table of Contents parsed from labeled pages.

    Output of substage 4a, saved as chapters/toc.json.
    """
    scan_id: str = Field(..., description="Scan identifier")
    toc_pages: List[int] = Field(..., description="PDF pages containing ToC")

    entries: List[TocEntry] = Field(..., description="All ToC entries in order")

    # Metadata
    parsing_method: Literal["llm", "regex"] = Field(..., description="How ToC was parsed")
    model_used: Optional[str] = Field(None, description="LLM model if used")
    cost: float = Field(..., ge=0.0, description="Cost of parsing (USD)")
    total_entries: int = Field(..., ge=0, description="Total entries parsed")
    low_confidence_entries: int = Field(..., ge=0, description="Entries with confidence < 0.8")
    timestamp: str = Field(..., description="When ToC was parsed")


# ==============================================================================
# Substage 4b: Page Mapping Schemas
# ==============================================================================

class PageMapping(BaseModel):
    """
    Single PDF page → Book page mapping.

    Derived from ToC + CHAPTER_HEADING labels + header validation.
    """
    pdf_page: int = Field(..., ge=1, description="PDF page number (1-indexed)")
    book_page: Optional[str] = Field(None, description="Book page number (as printed, e.g., 'ix', '45')")
    page_type: Literal["front_matter", "body", "back_matter", "unnumbered"] = Field(
        ..., description="Type of page content"
    )
    numbering_style: Optional[Literal["roman", "arabic", "none"]] = Field(
        None, description="Page numbering style"
    )

    # Validation
    toc_matched: bool = Field(..., description="Whether this mapping came from ToC match")
    header_validated: bool = Field(..., description="Whether header text confirms the page number")
    header_text: Optional[str] = Field(None, description="Header text found on page")


class PageMappingOutput(BaseModel):
    """
    Complete PDF ↔ Book page mapping.

    Output of substage 4b, saved as chapters/page_mapping.json.
    """
    scan_id: str = Field(..., description="Scan identifier")
    total_pages: int = Field(..., ge=1, description="Total PDF pages")

    mappings: List[PageMapping] = Field(..., description="All page mappings")

    # Region detection
    front_matter_pages: List[int] = Field(..., description="PDF pages in front matter (roman numerals)")
    body_pages: List[int] = Field(..., description="PDF pages in main body (arabic numerals)")
    back_matter_pages: List[int] = Field(..., description="PDF pages in back matter")

    # Statistics
    toc_match_count: int = Field(..., ge=0, description="Mappings from ToC matches")
    header_validated_count: int = Field(..., ge=0, description="Mappings validated by headers")
    unmapped_pages: int = Field(..., ge=0, description="Pages without book page numbers")

    timestamp: str = Field(..., description="When mapping was built")


# ==============================================================================
# Substage 4c: Boundary Detection Schemas
# ==============================================================================

class BoundaryCandidate(BaseModel):
    """
    Candidate chapter boundary detected from labels and ToC.

    Before LLM validation - these are initial detections.
    """
    pdf_page: int = Field(..., ge=1, description="PDF page where boundary detected")
    book_page: Optional[str] = Field(None, description="Book page number at boundary")

    # Detected information
    title: str = Field(..., min_length=1, description="Chapter title detected from label")
    detected_by: Literal["CHAPTER_HEADING_LABEL", "TOC_ONLY", "BOTH"] = Field(
        ..., description="How boundary was detected"
    )

    # ToC cross-validation
    toc_match: bool = Field(..., description="Whether title matches ToC entry")
    toc_title: Optional[str] = Field(None, description="Matching title from ToC")
    toc_book_page: Optional[str] = Field(None, description="Expected book page from ToC")
    toc_page_delta: Optional[int] = Field(None, description="Difference between detected and ToC page")

    # Confidence before LLM
    initial_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence before LLM validation")


class BoundaryCandidatesOutput(BaseModel):
    """
    All candidate chapter boundaries before LLM validation.

    Output of substage 4c, saved as chapters/boundary_candidates.json.
    """
    scan_id: str = Field(..., description="Scan identifier")
    candidates: List[BoundaryCandidate] = Field(..., description="All boundary candidates")

    total_candidates: int = Field(..., ge=0, description="Total boundaries detected")
    toc_matched_count: int = Field(..., ge=0, description="Candidates matching ToC")
    label_only_count: int = Field(..., ge=0, description="Boundaries from labels only (not in ToC)")
    toc_only_count: int = Field(..., ge=0, description="ToC entries without matching labels")

    timestamp: str = Field(..., description="When candidates were detected")


# ==============================================================================
# Substage 4d: LLM Validation Schemas
# ==============================================================================

class ValidationResult(BaseModel):
    """
    LLM validation result for a single boundary.

    LLM reviews 3 pages of context and confirms/corrects the boundary.
    """
    is_correct: bool = Field(..., description="LLM says boundary is correct")
    correct_pdf_page: int = Field(..., ge=1, description="Correct PDF page (may differ from candidate)")
    correct_title: str = Field(..., min_length=1, description="Correct chapter title")
    confidence: float = Field(..., ge=0.0, le=1.0, description="LLM confidence in validation")
    reasoning: str = Field(..., description="LLM explanation of decision")


class ValidatedBoundary(BaseModel):
    """
    Chapter boundary after LLM validation.

    Combines candidate detection with LLM confirmation/correction.
    """
    pdf_page: int = Field(..., ge=1, description="Final PDF page for boundary")
    book_page: Optional[str] = Field(None, description="Final book page number")
    title: str = Field(..., min_length=1, description="Final chapter title")

    # Provenance
    detected_by: str = Field(..., description="How initially detected")
    toc_match: bool = Field(..., description="Whether matched ToC")
    llm_validated: bool = Field(..., description="Whether LLM validated")
    llm_corrected: bool = Field(..., description="Whether LLM made corrections")

    # Confidence
    initial_confidence: float = Field(..., ge=0.0, le=1.0, description="Pre-validation confidence")
    final_confidence: float = Field(..., ge=0.0, le=1.0, description="Post-validation confidence")

    # LLM validation details
    validation_result: ValidationResult = Field(..., description="Full LLM validation output")


class ValidatedBoundariesOutput(BaseModel):
    """
    All chapter boundaries after LLM validation.

    Output of substage 4d, saved as chapters/boundaries_validated.json.
    """
    scan_id: str = Field(..., description="Scan identifier")
    boundaries: List[ValidatedBoundary] = Field(..., description="All validated boundaries")

    total_boundaries: int = Field(..., ge=0, description="Total chapter boundaries")
    llm_corrections_made: int = Field(..., ge=0, description="Boundaries corrected by LLM")
    high_confidence_count: int = Field(..., ge=0, description="Boundaries with confidence >= 0.9")
    low_confidence_count: int = Field(..., ge=0, description="Boundaries with confidence < 0.7")

    # Cost tracking
    model_used: str = Field(..., description="LLM model used for validation")
    validation_cost: float = Field(..., ge=0.0, description="Total LLM cost (USD)")
    avg_validation_time_seconds: float = Field(..., ge=0.0, description="Average time per validation")

    timestamp: str = Field(..., description="When validation completed")


# ==============================================================================
# Substage 4d: Vision Validation Schemas
# ==============================================================================

class VisionValidationResult(BaseModel):
    """
    Vision model validation result for a single boundary.

    Vision model reviews PDF images + JSON context and confirms/corrects the boundary.
    """
    is_correct: bool = Field(..., description="Vision model says boundary is correct")
    correct_pdf_page: int = Field(..., ge=1, description="Correct PDF page (may differ from candidate)")
    correct_title: str = Field(..., min_length=1, description="Correct boundary title")
    boundary_type: Literal["part", "chapter", "section", "subsection"] = Field(
        ..., description="Type of structural boundary"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Vision model confidence")
    visual_evidence: str = Field(..., description="What the model saw in images")
    reasoning: str = Field(..., description="Vision model explanation of decision")


# ==============================================================================
# Substage 4e: Chapter Assembly Schemas (Final Output)
# ==============================================================================

class StructuralBoundary(BaseModel):
    """
    Any structural boundary: Part, Chapter, Section, etc.

    Represents the complete hierarchy of book structure.
    Final output after assembling all validated boundaries.
    """
    boundary_num: int = Field(..., ge=1, description="Sequential boundary number")
    boundary_type: Literal["part", "chapter", "section", "subsection"] = Field(
        ..., description="Type of structural boundary"
    )
    title: str = Field(..., min_length=1, description="Boundary title")
    hierarchy_level: int = Field(..., ge=0, le=3, description="Hierarchy level (0=Part, 1=Chapter, 2=Section, 3=Subsection)")

    # PDF pages
    start_pdf_page: int = Field(..., ge=1, description="First PDF page of this section")
    end_pdf_page: int = Field(..., ge=1, description="Last PDF page of this section")

    # Book pages
    start_book_page: Optional[str] = Field(None, description="First book page (as printed)")
    end_book_page: Optional[str] = Field(None, description="Last book page (as printed)")

    # Metadata
    page_count: int = Field(..., ge=1, description="Total pages in this section")
    detected_by: str = Field(..., description="Detection provenance (TEXT_SEARCH, PAGE_MAPPING, etc.)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall confidence")
    toc_match: bool = Field(..., description="Whether boundary was in ToC")

    # Hierarchy
    parent_boundary_num: Optional[int] = Field(None, description="Parent boundary number (e.g., Chapter belongs to Part)")


# Legacy Chapter schema (for backward compatibility)
class Chapter(BaseModel):
    """
    Complete chapter definition with page ranges.

    DEPRECATED: Use StructuralBoundary instead.
    Kept for backward compatibility with existing code.
    """
    chapter_num: int = Field(..., ge=1, description="Sequential chapter number")
    title: str = Field(..., min_length=1, description="Chapter title")

    # PDF pages
    start_pdf_page: int = Field(..., ge=1, description="First PDF page of chapter")
    end_pdf_page: int = Field(..., ge=1, description="Last PDF page of chapter")

    # Book pages
    start_book_page: Optional[str] = Field(None, description="First book page (as printed)")
    end_book_page: Optional[str] = Field(None, description="Last book page (as printed)")

    # Metadata
    page_count: int = Field(..., ge=1, description="Total pages in chapter")
    detected_by: str = Field(..., description="Detection provenance")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall confidence")
    toc_match: bool = Field(..., description="Whether chapter was in ToC")


class BookStructure(BaseModel):
    """
    Complete book structure with full hierarchy.

    Final output of Stage 4, saved as chapters/structure.json.
    This is the canonical book structure used by downstream stages.

    Includes Parts, Chapters, Sections - the complete structural hierarchy.
    """
    scan_id: str = Field(..., description="Scan identifier")
    total_pages: int = Field(..., ge=1, description="Total PDF pages in book")

    # All structural boundaries in document order
    boundaries: List[StructuralBoundary] = Field(..., description="All structural boundaries (Parts, Chapters, Sections)")
    total_boundaries: int = Field(..., ge=0, description="Total number of boundaries")

    # Convenience views by type
    part_count: int = Field(..., ge=0, description="Number of Part boundaries")
    chapter_count: int = Field(..., ge=0, description="Number of Chapter boundaries")
    section_count: int = Field(..., ge=0, description="Number of Section boundaries")

    # Front/back matter
    front_matter_pages: List[int] = Field(..., description="Pages before first boundary")
    back_matter_pages: List[int] = Field(..., description="Pages after last boundary")

    # Detection metadata
    detection_method: str = Field(..., description="High-level detection strategy used")
    toc_available: bool = Field(..., description="Whether ToC was found and used")
    vision_validation_used: bool = Field(..., description="Whether vision model validation was performed")

    # Quality metrics
    avg_boundary_confidence: float = Field(..., ge=0.0, le=1.0, description="Average confidence across all boundaries")
    low_confidence_boundaries: int = Field(..., ge=0, description="Boundaries with confidence < 0.7")
    toc_mismatch_count: int = Field(..., ge=0, description="Boundaries where ToC page didn't match detected")

    # Cost tracking
    total_cost: float = Field(..., ge=0.0, description="Total cost for Stage 4 (USD)")
    processing_time_seconds: float = Field(..., ge=0.0, description="Total processing time")

    timestamp: str = Field(..., description="When structure detection completed")


# Legacy ChaptersOutput (for backward compatibility)
class ChaptersOutput(BaseModel):
    """
    Complete book chapter structure.

    DEPRECATED: Use BookStructure instead.
    Kept for backward compatibility with existing code.

    Final output of Stage 4, saved as chapters/chapters.json.
    This is the canonical book structure used by downstream stages.
    """
    scan_id: str = Field(..., description="Scan identifier")
    total_pages: int = Field(..., ge=1, description="Total PDF pages in book")

    chapters: List[Chapter] = Field(..., description="All chapters in order")
    total_chapters: int = Field(..., ge=0, description="Number of chapters")

    # Front/back matter
    front_matter_pages: List[int] = Field(..., description="Pages before first chapter")
    back_matter_pages: List[int] = Field(..., description="Pages after last chapter")

    # Detection metadata
    detection_method: str = Field(..., description="High-level detection strategy used")
    toc_available: bool = Field(..., description="Whether ToC was found and used")
    llm_validation_used: bool = Field(..., description="Whether LLM validation was performed")

    # Quality metrics
    avg_chapter_confidence: float = Field(..., ge=0.0, le=1.0, description="Average confidence across chapters")
    low_confidence_chapters: int = Field(..., ge=0, description="Chapters with confidence < 0.7")
    toc_mismatch_count: int = Field(..., ge=0, description="Chapters where ToC page didn't match detected")

    # Cost tracking
    total_cost: float = Field(..., ge=0.0, description="Total cost for Stage 4 (USD)")
    processing_time_seconds: float = Field(..., ge=0.0, description="Total processing time")

    timestamp: str = Field(..., description="When structure detection completed")
