from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from ..storage import LinkTocStageStorage
from ..schemas import LinkTocReportEntry


def generate_report(
    storage: BookStorage,
    logger: PipelineLogger,
    stage_storage: LinkTocStageStorage
):
    """Generate CSV report from linked_toc.json."""

    # Load linked ToC
    linked_toc = stage_storage.load_linked_toc(storage)

    if not linked_toc:
        logger.warning("No linked ToC found to generate report from")
        return

    # Convert to report entries
    report_entries = []

    for idx, entry in enumerate(linked_toc.entries):
        # Truncate reasoning for CSV readability
        reasoning_truncated = entry.agent_reasoning[:200] if entry.agent_reasoning else ""

        report_entry = LinkTocReportEntry(
            toc_index=idx,
            toc_title=entry.title,
            printed_page=entry.printed_page_number or "N/A",
            scan_page=str(entry.scan_page) if entry.scan_page else "NOT_FOUND",
            confidence=entry.link_confidence,
            search_strategy="agent_search",  # Could be enhanced to track strategy
            iterations=entry.agent_iterations,
            reasoning=reasoning_truncated
        )

        report_entries.append(report_entry)

    # Save CSV using storage helper
    stage_storage.save_report(storage, report_entries)

    report_path = stage_storage.get_report_path(storage)
    logger.info(f"Report generated: {report_path}")
    logger.info(f"  Total entries: {len(report_entries)}")
    logger.info(f"  Found: {sum(1 for e in report_entries if e.scan_page != 'NOT_FOUND')}")
