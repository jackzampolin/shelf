"""
Pydantic schemas for build-structure stage.

Three-phase processing model:
1. Phase 1: LLM analyzes report.csv -> DraftMetadata (unvalidated)
2. Phase 2: Validate against ground truth -> ValidationResult
3. Phase 3: Combine into BookStructureMetadata (final output)
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Core Building Blocks
# ============================================================================

class PageRange(BaseModel):
    """Inclusive page range [start_page, end_page]."""
    start_page: int = Field(..., ge=1, description="First page number (inclusive)")
    end_page: int = Field(..., ge=1, description="Last page number (inclusive)")

    def __len__(self) -> int:
        """Return number of pages in range."""
        return self.end_page - self.start_page + 1

    def contains(self, page_num: int) -> bool:
        """Check if page number is in range."""
        return self.start_page <= page_num <= self.end_page


class LabeledPageRange(BaseModel):
    """Page range with a label for 'other' front/back matter sections."""
    label: str = Field(..., min_length=1, description="Section label (e.g., 'Timeline', 'Acknowledgments')")
    page_range: PageRange = Field(..., description="Page range for this section")

    @classmethod
    def from_dict(cls, data):
        """Handle LLM returning page_range fields at top level."""
        if "page_range" not in data and "start_page" in data:
            # LLM returned flat structure: {label, start_page, end_page}
            return cls(
                label=data["label"],
                page_range=PageRange(start_page=data["start_page"], end_page=data["end_page"])
            )
        return cls(**data)

    @property
    def start_page(self) -> int:
        """Convenience accessor for first page."""
        return self.page_range.start_page

    @property
    def end_page(self) -> int:
        """Convenience accessor for last page."""
        return self.page_range.end_page


class BoundaryVerificationResult(BaseModel):
    """Result from LLM verification of chapter/section boundaries."""
    is_boundary: bool = Field(..., description="Whether this page contains the expected heading")
    detected_title: Optional[str] = Field(None, description="Exact title text found on page, or null if no heading")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    reasoning: str = Field(..., min_length=1, description="Brief explanation of the decision")


class Section(BaseModel):
    """Subsection within a chapter."""
    title: str = Field(..., min_length=1, description="Section heading text")
    page_range: PageRange = Field(..., description="Pages this section spans")
    level: int = Field(..., ge=1, le=3, description="Nesting level (1=top, 2=sub, 3=subsub)")

    @field_validator('title', mode='before')
    @classmethod
    def handle_null_title(cls, v):
        """Convert null title to placeholder."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return "Untitled Section"
        return v


class Part(BaseModel):
    """Book part (major division containing chapters)."""
    part_number: int = Field(..., ge=1, description="Part number (sequential)")
    title: str = Field(..., min_length=1, description="Part title")
    page_range: PageRange = Field(..., description="Pages this part spans")

    @field_validator('title', mode='before')
    @classmethod
    def handle_null_title(cls, v):
        """Convert null title to placeholder."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return "Untitled Part"
        return v

    @property
    def start_page(self) -> int:
        """Convenience accessor for first page."""
        return self.page_range.start_page

    @property
    def end_page(self) -> int:
        """Convenience accessor for last page."""
        return self.page_range.end_page


class Chapter(BaseModel):
    """Book chapter with optional sections."""
    chapter_number: int = Field(..., ge=1, description="Chapter number (sequential)")
    title: str = Field(..., min_length=1, description="Chapter title")
    page_range: PageRange = Field(..., description="Pages this chapter spans")
    part_number: Optional[int] = Field(None, ge=1, description="Parent part number (if book has parts)")
    sections: List[Section] = Field(default_factory=list, description="Subsections within chapter")

    @field_validator('title', mode='before')
    @classmethod
    def handle_null_title(cls, v):
        """Convert null title to placeholder."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return "Untitled Chapter"
        return v

    @property
    def start_page(self) -> int:
        """Convenience accessor for first page."""
        return self.page_range.start_page

    @property
    def end_page(self) -> int:
        """Convenience accessor for last page."""
        return self.page_range.end_page


# ============================================================================
# Front Matter / Back Matter
# ============================================================================

class FrontMatter(BaseModel):
    """
    Front matter components (before main body).

    All sections use LabeledPageRange to capture descriptive labels
    (e.g., "Title Page", "Preface to Second Edition", "Contents").
    """
    title_page: Optional[LabeledPageRange] = Field(None, description="Title page (half-title, full title)")
    toc: Optional[LabeledPageRange] = Field(None, description="Table of Contents")
    preface: Optional[LabeledPageRange] = Field(None, description="Preface, Author's Note, etc.")
    introduction: Optional[LabeledPageRange] = Field(None, description="Introduction, Prologue")
    other: List[LabeledPageRange] = Field(default_factory=list, description="Other front matter (dedication, foreword, copyright, etc.)")

    page_numbering_style: Optional[Literal["roman", "arabic", "none", "mixed"]] = Field(
        None, description="Page numbering style in front matter (mixed if switches between styles)"
    )

    @field_validator('title_page', 'toc', 'preface', 'introduction', mode='before')
    @classmethod
    def handle_labeled_page_range(cls, v, info):
        """Handle LLM returning flat structure for labeled sections."""
        if v is None:
            return None
        if isinstance(v, dict):
            if "page_range" not in v and "start_page" in v:
                # Flat structure without label: {start_page, end_page}
                # OR flat structure with label: {label, start_page, end_page}
                field_name = info.field_name
                default_labels = {
                    'title_page': 'Title Page',
                    'toc': 'Table of Contents',
                    'preface': 'Preface',
                    'introduction': 'Introduction'
                }
                label = v.get("label", default_labels.get(field_name, field_name.replace('_', ' ').title()))
                return LabeledPageRange(
                    label=label,
                    page_range=PageRange(start_page=v["start_page"], end_page=v["end_page"])
                )
            else:
                # Nested structure: {label, page_range: {start_page, end_page}}
                return LabeledPageRange(**v)
        return v

    @field_validator('other', mode='before')
    @classmethod
    def handle_other_sections(cls, v):
        """Handle LLM returning flat structure for other sections."""
        if not v:
            return []
        result = []
        for item in v:
            if isinstance(item, dict):
                if "page_range" not in item and "start_page" in item:
                    # Flat structure: {label, start_page, end_page}
                    result.append(LabeledPageRange(
                        label=item.get("label", "Other"),
                        page_range=PageRange(start_page=item["start_page"], end_page=item["end_page"])
                    ))
                else:
                    # Nested structure: {label, page_range: {start_page, end_page}}
                    result.append(LabeledPageRange(**item))
            else:
                result.append(item)
        return result


class BackMatter(BaseModel):
    """
    Back matter components (after main body).

    All sections use LabeledPageRange to capture descriptive labels
    (e.g., "Appendix A: Statistics", "Bibliography", "Index of Names").
    """
    appendices: List[LabeledPageRange] = Field(default_factory=list, description="Appendix sections with labels (A, B, etc.)")
    notes: Optional[LabeledPageRange] = Field(None, description="Notes, Endnotes, References")
    bibliography: Optional[LabeledPageRange] = Field(None, description="Bibliography, Works Cited")
    index: Optional[LabeledPageRange] = Field(None, description="Index, Indices")
    other: List[LabeledPageRange] = Field(default_factory=list, description="Other back matter (epilogue, afterword, etc.)")

    page_numbering_style: Optional[Literal["roman", "arabic", "none", "mixed"]] = Field(
        None, description="Page numbering style in back matter (mixed if switches between styles)"
    )

    @field_validator('notes', 'bibliography', 'index', mode='before')
    @classmethod
    def handle_labeled_page_range(cls, v, info):
        """Handle LLM returning flat structure for labeled sections."""
        if v is None:
            return None
        if isinstance(v, dict):
            if "page_range" not in v and "start_page" in v:
                # Flat structure without label: {start_page, end_page}
                # OR flat structure with label: {label, start_page, end_page}
                field_name = info.field_name
                default_labels = {
                    'notes': 'Notes',
                    'bibliography': 'Bibliography',
                    'index': 'Index'
                }
                label = v.get("label", default_labels.get(field_name, field_name.replace('_', ' ').title()))
                return LabeledPageRange(
                    label=label,
                    page_range=PageRange(start_page=v["start_page"], end_page=v["end_page"])
                )
            else:
                # Nested structure: {label, page_range: {start_page, end_page}}
                return LabeledPageRange(**v)
        return v

    @field_validator('appendices', 'other', mode='before')
    @classmethod
    def handle_labeled_list(cls, v):
        """Handle LLM returning flat structure for list sections."""
        if not v:
            return []
        result = []
        for item in v:
            if isinstance(item, dict):
                if "page_range" not in item and "start_page" in item:
                    # Flat structure: {label, start_page, end_page}
                    result.append(LabeledPageRange(
                        label=item.get("label", ""),
                        page_range=PageRange(start_page=item["start_page"], end_page=item["end_page"])
                    ))
                else:
                    # Nested structure: {label, page_range: {start_page, end_page}}
                    result.append(LabeledPageRange(**item))
            else:
                result.append(item)
        return result


# ============================================================================
# Phase 1a: Table of Contents
# ============================================================================

class ToCEntry(BaseModel):
    """Single entry in table of contents."""
    chapter_number: Optional[int] = Field(None, ge=1, description="Chapter number if present")
    title: str = Field(..., min_length=1, description="Chapter/section title as shown in ToC")
    printed_page_number: Optional[int] = Field(None, ge=1, description="PRINTED page number from ToC (NOT scan page number)")
    level: int = Field(1, ge=1, le=3, description="Hierarchy level (1=chapter, 2=section, 3=subsection)")


class TableOfContents(BaseModel):
    """Parsed table of contents structure."""
    entries: List[ToCEntry] = Field(..., description="All ToC entries in order")
    toc_page_range: PageRange = Field(..., description="Pages where ToC appears")
    total_chapters: int = Field(..., ge=0, description="Number of chapter entries")
    total_sections: int = Field(..., ge=0, description="Number of section/subsection entries")
    parsing_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in parsing accuracy")
    notes: List[str] = Field(default_factory=list, description="Parsing notes or warnings")


# ============================================================================
# Phase 1.5: Heading Extraction
# ============================================================================

class HeadingEntry(BaseModel):
    """Single heading extracted from a page marked as has_chapter_heading=True."""
    page_num: int = Field(..., ge=1, description="SCAN page number where heading appears")
    heading_text: str = Field(..., min_length=1, description="Extracted heading text (e.g., 'Part IV', '17', 'Chapter 1')")
    is_part: bool = Field(False, description="True if heading contains 'Part' keyword")
    printed_page_number: Optional[str] = Field(None, description="PRINTED page number if available (may be roman numeral like 'xiv' or arabic like '42')")


class HeadingData(BaseModel):
    """Phase 1.5 output: Extracted headings from all chapter heading pages."""
    headings: List[HeadingEntry] = Field(..., description="All extracted headings in order")
    total_headings: int = Field(..., ge=0, description="Total number of headings extracted")
    part_count: int = Field(0, ge=0, description="Number of headings marked as parts")
    chapter_count: int = Field(0, ge=0, description="Number of headings not marked as parts")


# ============================================================================
# Phase 1b: Draft Metadata (LLM Output)
# ============================================================================

class DraftMetadata(BaseModel):
    """Phase 1 output: Unvalidated structure draft from LLM analysis of report.csv."""

    front_matter: FrontMatter = Field(..., description="Front matter structure")
    parts: Optional[List[Part]] = Field(None, description="Parts (major divisions) if book uses them")
    chapters: List[Chapter] = Field(..., description="All chapters in order")
    back_matter: BackMatter = Field(..., description="Back matter structure")

    # Summary stats
    total_parts: int = Field(0, ge=0, description="Total number of parts (0 if book has no parts)")
    total_chapters: int = Field(..., ge=0, description="Total number of chapters")
    total_sections: int = Field(..., ge=0, description="Total number of sections across all chapters")
    body_page_range: PageRange = Field(..., description="Main body content (first to last chapter)")

    # Numbering patterns detected
    page_numbering_changes: List[dict] = Field(
        default_factory=list,
        description="Detected changes in page numbering style (e.g., roman -> arabic)"
    )


# ============================================================================
# Phase 2: Validation Result
# ============================================================================

class ValidationIssue(BaseModel):
    """Single validation issue discovered during Phase 2."""

    severity: Literal["error", "warning", "info"] = Field(..., description="Issue severity")
    issue_type: str = Field(..., min_length=1, description="Type of issue (e.g., 'missing_chapter_heading')")
    message: str = Field(..., min_length=1, description="Human-readable description")
    page_num: Optional[int] = Field(None, ge=1, description="Page number where issue occurs")
    chapter_num: Optional[int] = Field(None, ge=1, description="Chapter number if relevant")

    # Evidence
    expected: Optional[str] = Field(None, description="What was expected")
    actual: Optional[str] = Field(None, description="What was found")


class ValidationResult(BaseModel):
    """Phase 2 output: Validation results from checking draft against ground truth."""

    is_valid: bool = Field(..., description="Overall validation passed (no errors)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")

    issues: List[ValidationIssue] = Field(default_factory=list, description="All validation issues")

    # Issue counts by severity
    error_count: int = Field(0, ge=0, description="Number of blocking errors")
    warning_count: int = Field(0, ge=0, description="Number of warnings")
    info_count: int = Field(0, ge=0, description="Number of informational messages")

    # What was validated
    pages_validated: int = Field(0, ge=0, description="Number of pages checked")
    chapters_validated: int = Field(0, ge=0, description="Number of chapters checked")


# ============================================================================
# Phase 3: Final Book Structure Metadata
# ============================================================================

class BookStructureMetadata(BaseModel):
    """Final output: Validated book structure metadata (saved as metadata.json)."""

    # Core structure (from DraftMetadata, validated)
    front_matter: FrontMatter = Field(..., description="Front matter structure")
    parts: Optional[List[Part]] = Field(None, description="Parts (major divisions) if book uses them")
    chapters: List[Chapter] = Field(..., description="All chapters in order")
    back_matter: BackMatter = Field(..., description="Back matter structure")

    # Validation info
    validation: ValidationResult = Field(..., description="Validation results")

    # Metadata
    structure_extracted_at: str = Field(..., description="ISO timestamp when extracted")
    structure_cost_usd: float = Field(..., ge=0.0, description="Total cost for structure extraction")
    total_pages: int = Field(..., ge=1, description="Total pages in book")

    # Summary (convenience)
    total_parts: int = Field(0, ge=0, description="Total number of parts")
    total_chapters: int = Field(..., ge=0, description="Total number of chapters")
    total_sections: int = Field(..., ge=0, description="Total number of sections")
    body_page_range: PageRange = Field(..., description="Main body content range")
