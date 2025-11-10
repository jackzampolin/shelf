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
            whitespace = page_data.get('whitespace', {})
            text_continuation = page_data.get('text_continuation', {})
            heading = page_data.get('heading', {})
            header = page_data.get('header', {})
            footer = page_data.get('footer', {})
            ornamental_break = page_data.get('ornamental_break', {})
            footnotes = page_data.get('footnotes', {})
            page_number_obs = page_data.get('page_number', {})

            report_row = report_schema(
                scan_page_number=page_data.get('scan_page_number', page_num),

                # Whitespace
                whitespace_zones=','.join(whitespace.get('zones', [])) if whitespace.get('zones') else 'none',
                whitespace_conf=whitespace.get('confidence', 0.0),

                # Text continuation
                continues_from_prev=text_continuation.get('from_previous', False),
                continues_to_next=text_continuation.get('to_next', False),
                continuation_conf=text_continuation.get('confidence', 0.0),

                # Heading
                heading_exists=heading.get('exists', False),
                heading_text=heading.get('text', '') or '',
                heading_position=heading.get('position', '') or '',
                heading_conf=heading.get('confidence', 0.0),

                # Header
                header_exists=header.get('exists', False),
                header_text=header.get('text', '') or '',
                header_conf=header.get('confidence', 0.0),

                # Footer
                footer_exists=footer.get('exists', False),
                footer_text=footer.get('text', '') or '',
                footer_position=footer.get('position', '') or '',
                footer_conf=footer.get('confidence', 0.0),

                # Ornamental break
                ornamental_break=ornamental_break.get('exists', False),
                ornamental_break_position=ornamental_break.get('position', '') or '',
                ornamental_break_conf=ornamental_break.get('confidence', 0.0),

                # Footnotes
                footnotes_exist=footnotes.get('exists', False),
                footnotes_conf=footnotes.get('confidence', 0.0),

                # Page number
                page_num_exists=page_number_obs.get('exists', False),
                page_num_value=page_number_obs.get('number', '') or '',
                page_num_position=page_number_obs.get('position', '') or '',
                page_num_conf=page_number_obs.get('confidence', 0.0),
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
