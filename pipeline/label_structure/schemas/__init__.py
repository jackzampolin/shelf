from .mechanical import HeadingItem, PatternHints, MechanicalExtractionOutput
from .structure import (
    HeaderObservation,
    FooterObservation,
    PageNumberObservation,
    StructuralMetadataOutput,
)
from .annotations import (
    ReferenceMarker,
    FootnoteContent,
    CrossReference,
    AnnotationsOutput,
)
from .unified import UnifiedExtractionOutput
from .merged_output import LabelStructurePageOutput
from .page_report import LabelStructurePageReport

# Legacy schemas (will be removed after migration)
from .llm_response import StructureExtractionResponse


__all__ = [
    # Mechanical extraction
    "HeadingItem",
    "PatternHints",
    "MechanicalExtractionOutput",
    # Structural metadata (shared types used by unified)
    "HeaderObservation",
    "FooterObservation",
    "PageNumberObservation",
    "StructuralMetadataOutput",  # Legacy - kept for backwards compat
    # Content annotations (shared types used by unified)
    "ReferenceMarker",
    "FootnoteContent",
    "CrossReference",
    "AnnotationsOutput",  # Legacy - kept for backwards compat
    # Unified extraction (replaces separate structure + annotations)
    "UnifiedExtractionOutput",
    # Merged output
    "LabelStructurePageOutput",
    # Report
    "LabelStructurePageReport",
    # Legacy
    "StructureExtractionResponse",
]
