import csv
from ..schemas import LinkTocReportEntry, LinkedTableOfContents

def generate_report(tracker, **kwargs):
    """Generate CSV report from linked_toc.json."""

    # Access storage and logger through tracker
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    # Load linked ToC
    data = stage_storage.load_file("linked_toc.json")
    linked_toc = LinkedTableOfContents(**data) if data else None

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

    # Save CSV report
    report_path = stage_storage.output_dir / "report.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "toc_index", "toc_title", "printed_page", "scan_page",
            "confidence", "search_strategy", "iterations", "reasoning"
        ])
        writer.writeheader()
        for entry in report_entries:
            writer.writerow(entry.model_dump())

    logger.info(f"Report generated: {report_path}")
    logger.info(f"  Total entries: {len(report_entries)}")
    logger.info(f"  Found: {sum(1 for e in report_entries if e.scan_page != 'NOT_FOUND')}")
