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
    """Generate CSV report summarizing page-level structural metadata.

    Shows: page numbers, regions, boundaries, confidence scores.
    Useful for: validating ToC, checking page number sequences, spotting issues.
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

            # Extract structural boundary data
            boundary = page_data.get('structural_boundary', {})

            # Build report row
            report_row = report_schema(
                page_num=page_num,
                printed_page_number=page_data.get('printed_page_number'),
                numbering_style=page_data.get('numbering_style', 'none'),
                page_number_location=page_data.get('page_number_location', 'none'),
                page_region=page_data.get('page_region', 'body'),
                is_boundary=boundary.get('is_boundary', False),
                boundary_type=boundary.get('suggested_type'),
                whitespace=boundary.get('whitespace_amount', 'minimal'),
                heading_size=boundary.get('heading_size', 'none'),
                has_toc=page_data.get('has_table_of_contents', False),
                page_num_conf=page_data.get('page_number_confidence', 1.0),
                region_conf=page_data.get('page_region_confidence', 0.5),
                boundary_conf=boundary.get('boundary_confidence', 0.0),
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
