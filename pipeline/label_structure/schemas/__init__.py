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
from .merged_output import LabelStructurePageOutput
from .page_report import LabelStructurePageReport

# Legacy schemas (will be removed after migration)
from .llm_response import StructureExtractionResponse


__all__ = [
    # Mechanical extraction
    "HeadingItem",
    "PatternHints",
    "MechanicalExtractionOutput",
    # Structural metadata
    "HeaderObservation",
    "FooterObservation",
    "PageNumberObservation",
    "StructuralMetadataOutput",
    # Content annotations
    "ReferenceMarker",
    "FootnoteContent",
    "CrossReference",
    "AnnotationsOutput",
    # Merged output
    "LabelStructurePageOutput",
    # Report
    "LabelStructurePageReport",
    # Legacy
    "StructureExtractionResponse",
]
