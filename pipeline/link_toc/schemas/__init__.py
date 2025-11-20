from .agent_result import AgentResult
from .linked_toc_entry import LinkedToCEntry
from .linked_table_of_contents import LinkedTableOfContents
from .report import LinkTocReportEntry
from .pattern_analysis import PatternAnalysis, CandidateHeading
from .heading_decision import HeadingDecision
from .enriched_toc import EnrichedToCEntry, EnrichedTableOfContents

__all__ = [
    "AgentResult",  # Internal: per-agent search result
    "LinkedToCEntry",  # Output: enriched ToC entry
    "LinkedTableOfContents",  # Output: enriched ToC (main stage output)
    "LinkTocReportEntry",  # Report: CSV row
    "PatternAnalysis",  # Phase 2: Pattern analysis result
    "CandidateHeading",  # Phase 2: Candidate heading for evaluation
    "HeadingDecision",  # Phase 3: Evaluation decision per heading
    "EnrichedToCEntry",  # Phase 4: Entry in enriched ToC
    "EnrichedTableOfContents",  # Phase 4: Final enriched ToC output
]
