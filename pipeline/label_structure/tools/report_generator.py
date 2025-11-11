import csv

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


def generate_report(
    storage: BookStorage,
    logger: PipelineLogger,
    report_schema,
    stage_name: str,
):
    logger.info("Generating report.csv from page outputs")

    stage_storage = storage.stage(stage_name)

    page_nums = stage_storage.list_pages(extension='json')

    if not page_nums:
        logger.warning("No completed pages found")
        return

    report_rows = []
    for page_num in page_nums:
        try:
            page_data = stage_storage.load_page(page_num)
            if not page_data:
                continue

            # Extract observations
            header = page_data.get('header', {})
            footer = page_data.get('footer', {})
            page_number = page_data.get('page_number', {})
            headings = page_data.get('headings', {})

            # Format headings for CSV
            heading_items = headings.get('headings', [])
            headings_text = '|'.join(h.get('text', '') for h in heading_items) if heading_items else ''
            headings_levels = '|'.join(str(h.get('level', '')) for h in heading_items) if heading_items else ''

            report_row = report_schema(
                page_num=page_data.get('page_num', page_num),

                # Header
                header_present=header.get('present', False),
                header_text=header.get('text', '') or '',
                header_conf=header.get('confidence', 'low'),
                header_source=header.get('source_provider', ''),

                # Footer
                footer_present=footer.get('present', False),
                footer_text=footer.get('text', '') or '',
                footer_conf=footer.get('confidence', 'low'),
                footer_source=footer.get('source_provider', ''),

                # Page number
                page_num_present=page_number.get('present', False),
                page_num_value=page_number.get('number', '') or '',
                page_num_location=page_number.get('location', '') or '',
                page_num_conf=page_number.get('confidence', 'low'),
                page_num_source=page_number.get('source_provider', ''),

                # Headings
                headings_present=headings.get('present', False),
                headings_count=len(heading_items),
                headings_text=headings_text,
                headings_levels=headings_levels,
                headings_conf=headings.get('confidence', 'low'),
                headings_source=headings.get('source_provider', ''),
            )
            report_rows.append(report_row.model_dump())
        except Exception as e:
            logger.warning(f"Failed to process page {page_num}", error=str(e))
            continue

    if not report_rows:
        logger.warning("No valid pages to write to report")
        return

    report_path = stage_storage.output_dir / "report.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, 'w', newline='') as f:
        fieldnames = list(report_rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    logger.info(f"Report written: {report_path} ({len(report_rows)} pages)")
