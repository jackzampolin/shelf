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

    output_files = stage_storage.list_output_pages(extension='json')

    if not output_files:
        logger.warning("No completed pages found")
        return

    # Extract page numbers from filenames
    page_nums = []
    for file_path in output_files:
        # Extract page number from page_0001.json -> 1
        page_num_str = file_path.stem.split('_')[1]
        page_nums.append(int(page_num_str))

    page_nums = sorted(page_nums)

    report_rows = []
    for page_num in page_nums:
        try:
            page_data = stage_storage.load_page(page_num)
            if not page_data:
                continue

            visual = page_data.get('visual_signals', {})
            textual = page_data.get('textual_signals', {})

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

    report_path = stage_storage.output_dir / "report.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, 'w', newline='') as f:
        fieldnames = list(report_rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    logger.info(f"Report written: {report_path} ({len(report_rows)} pages)")
