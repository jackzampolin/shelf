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
    logger.info("Generating report.csv from metrics")

    stage_storage_obj = storage.stage(stage_name)
    all_metrics = stage_storage_obj.metrics_manager.get_all()

    if not all_metrics:
        logger.warning("No page metrics found")
        return

    report_rows = []
    for page_key, metrics in sorted(all_metrics.items(), key=lambda x: int(x[0].split('_')[1]) if '_' in x[0] else 0):
        try:
            page_num = int(page_key.split('_')[1])
        except (IndexError, ValueError):
            continue

        try:
            report_row = report_schema(
                page_num=page_num,
                printed_page_number=metrics.get('printed_page_number'),
                numbering_style=metrics.get('numbering_style'),
                page_region=metrics.get('page_region'),
                page_number_extracted=metrics.get('page_number_extracted', False),
                page_region_classified=metrics.get('page_region_classified', False),
                total_blocks_classified=metrics.get('total_blocks_classified', 0),
                avg_classification_confidence=metrics.get('avg_classification_confidence', 0.0),
                has_chapter_heading=metrics.get('has_chapter_heading', False),
                has_section_heading=metrics.get('has_section_heading', False),
                chapter_heading_text=metrics.get('chapter_heading_text'),
            )
            report_rows.append(report_row.model_dump())
        except Exception as e:
            logger.warning(f"Failed to process metrics for page {page_num}", error=str(e))
            continue

    if not report_rows:
        logger.warning("No valid metrics to write to report")
        return

    report_path = stage_storage.get_report_path(storage)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, 'w', newline='') as f:
        fieldnames = list(report_rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    logger.info(f"Report written: {report_path} ({len(report_rows)} pages)")
