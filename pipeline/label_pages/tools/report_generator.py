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

            # Build report row
            report_row = report_schema(
                page_num=page_num,
                is_boundary=page_data.get('is_boundary', False),
                boundary_conf=page_data.get('boundary_confidence', 0.0),
                boundary_position=page_data.get('boundary_position', 'none'),
                whitespace=visual.get('whitespace_amount', 'minimal'),
                page_density=visual.get('page_density', 'moderate'),
                starts_mid_sentence=textual.get('starts_mid_sentence', False),
                appears_to_continue=textual.get('appears_to_continue', False),
                has_boundary_marker=textual.get('has_boundary_marker', False),
                boundary_marker_text=textual.get('boundary_marker_text', ''),
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
