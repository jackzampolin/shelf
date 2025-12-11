from .linked_toc_entry import LinkedToCEntry
from .linked_table_of_contents import LinkedTableOfContents
from .report import LinkTocReportEntry
from .pattern_analysis import (
    PatternAnalysis,
    CandidateHeading,
    DiscoveredPattern,
    MissingEntry,
    MissingCandidateHeading,  # Backwards compat alias for MissingEntry
    ExcludedPageRange,
)
from .heading_decision import HeadingDecision
from .enriched_toc import EnrichedToCEntry, EnrichedTableOfContents
from .coverage_report import PageGap, GapInvestigation, CoverageReport

__all__ = [
    "LinkedToCEntry",
    "LinkedTableOfContents",
    "LinkTocReportEntry",
    "PatternAnalysis",
    "CandidateHeading",
    "DiscoveredPattern",
    "MissingEntry",
    "MissingCandidateHeading",
    "ExcludedPageRange",
    "HeadingDecision",
    "EnrichedToCEntry",
    "EnrichedTableOfContents",
    "PageGap",
    "GapInvestigation",
    "CoverageReport",
]
