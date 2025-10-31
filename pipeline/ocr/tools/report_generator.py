import csv
from pathlib import Path
from typing import Optional

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger

from ..storage import OCRStageStorage
from ..schemas import OCRPageReport


def generate_report(
    storage: BookStorage,
    checkpoint: CheckpointManager,
    logger: PipelineLogger,
    ocr_storage: OCRStageStorage,
    report_schema,  # OCRPageReport
) -> Optional[Path]:
    logger.info("Generating report.csv from checkpoint metrics...")

    all_metrics = checkpoint.get_all_metrics()

    if not all_metrics:
        logger.warning("No metrics to report (no pages processed)")
        return None

    report_rows = []
    for page_num, metrics_dict in sorted(all_metrics.items()):
        try:
            report_row = {
                "page_num": int(page_num),
                "confidence_mean": metrics_dict.get("confidence", 0.0),  # Vision confidence or 0 if auto-selected
                "blocks_detected": metrics_dict.get("blocks_detected", 0),
            }

            validated = report_schema(**report_row)
            report_rows.append(validated.model_dump())

        except Exception as e:
            logger.warning(f"Failed to extract report for page {page_num}: {e}")
            continue

    if not report_rows:
        logger.error("No valid report rows generated")
        return None

    report_path = storage.book_dir / ocr_storage.stage_name / "report.csv"

    try:
        with open(report_path, 'w', newline='') as f:
            if report_rows:
                fieldnames = list(report_rows[0].keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(report_rows)

        logger.info(f"✓ Generated report: {report_path} ({len(report_rows)} pages)")
        return report_path

    except Exception as e:
        logger.error(f"Failed to write report: {e}")
        return None
