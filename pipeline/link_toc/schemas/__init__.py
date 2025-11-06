from .agent_result import AgentResult
from .linked_toc_entry import LinkedToCEntry
from .linked_table_of_contents import LinkedTableOfContents
from .report import LinkTocReportEntry

__all__ = [
    "AgentResult",  # Internal: per-agent search result
    "LinkedToCEntry",  # Output: enriched ToC entry
    "LinkedTableOfContents",  # Output: enriched ToC (main stage output)
    "LinkTocReportEntry",  # Report: CSV row
]
