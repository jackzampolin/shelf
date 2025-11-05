import csv

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


def generate_report(
    storage: BookStorage,
    logger: PipelineLogger,
    stage_storage,
    report_schema,
    stage_name: str,
):
    """Generate CSV report summarizing structural boundary detection.

    Shows: boundary status, confidence, visual/textual signals, heading info.
    Useful for: validating ToC entries, checking boundary detection accuracy.
    """
    logger.info("Generating report.csv from page outputs")

    stage_storage_obj = storage.stage(stage_name)

    # Load all completed pages
    completed_pages = stage_storage.list_completed_pages(storage)

    if not completed_pages:
        logger.warning("No completed pages found")
        return

    report_rows = []
    for page_num in sorted(completed_pages):
        try:
            # Load page output
            page_data = stage_storage_obj.load_page(page_num)
            if not page_data:
                continue

            # Extract signals
            visual = page_data.get('visual_signals', {})
            textual = page_data.get('textual_signals', {})
            heading = page_data.get('heading_info') or {}

            # Build report row
            report_row = report_schema(
                page_num=page_num,
                is_boundary=page_data.get('is_boundary', False),
                boundary_conf=page_data.get('boundary_confidence', 0.0),
                heading_text=heading.get('heading_text'),
                heading_type=heading.get('suggested_type'),
                type_conf=heading.get('type_confidence', 0.0),
                whitespace=visual.get('whitespace_amount', 'minimal'),
                heading_size=visual.get('heading_size', 'none'),
                heading_visible=visual.get('heading_visible', False),
                starts_with_heading=textual.get('starts_with_heading', False),
                appears_to_continue=textual.get('appears_to_continue', False),
                first_line=textual.get('first_line_preview', '')[:50],  # Truncate for CSV
            )
            report_rows.append(report_row.model_dump())
        except Exception as e:
            logger.warning(f"Failed to process page {page_num}", error=str(e))
            continue

    if not report_rows:
        logger.warning("No valid pages to write to report")
        return

    # Write CSV
    report_path = stage_storage.get_report_path(storage)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, 'w', newline='') as f:
        fieldnames = list(report_rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    logger.info(f"Report written: {report_path} ({len(report_rows)} pages)")
