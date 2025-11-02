import csv
from pathlib import Path

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
                total_corrections=metrics.get('total_corrections', 0),
                avg_confidence=metrics.get('avg_confidence', 0.0),
                text_similarity_ratio=metrics.get('text_similarity_ratio', 1.0),
                characters_changed=metrics.get('characters_changed', 0),
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
