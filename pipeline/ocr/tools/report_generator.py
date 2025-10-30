"""
Report generation for OCR (Phase 4).

Generates report.csv from checkpoint metrics after all pages are complete.
"""

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
    """
    Generate quality-focused report.csv from checkpoint metrics (Phase 4).

    Extracts report fields from checkpoint and writes to CSV for analysis.

    Args:
        storage: BookStorage instance
        checkpoint: CheckpointManager instance
        logger: PipelineLogger instance
        ocr_storage: OCRStageStorage instance
        report_schema: Pydantic schema for report (OCRPageReport)

    Returns:
        Path to generated report.csv, or None if failed
    """
    logger.info("Generating report.csv from checkpoint metrics...")

    # Get all page metrics from checkpoint
    all_metrics = checkpoint.get_all_metrics()

    if not all_metrics:
        logger.warning("No metrics to report (no pages processed)")
        return None

    # Extract report fields from checkpoint metrics
    report_rows = []
    for page_num, metrics_dict in sorted(all_metrics.items()):
        try:
            # Build report row from checkpoint data
            report_row = {
                "page_num": int(page_num),
                "confidence_mean": metrics_dict.get("confidence", 0.0),  # Vision confidence or 0 if auto-selected
                "blocks_detected": metrics_dict.get("blocks_detected", 0),
            }

            # Validate against report schema
            validated = report_schema(**report_row)
            report_rows.append(validated.model_dump())

        except Exception as e:
            logger.warning(f"Failed to extract report for page {page_num}: {e}")
            continue

    if not report_rows:
        logger.error("No valid report rows generated")
        return None

    # Write to CSV
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
