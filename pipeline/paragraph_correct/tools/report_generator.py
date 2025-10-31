"""
Report Generator

Generates report.csv from checkpoint metrics.
Filters metrics to show only quality-relevant data.
"""

import csv
from pathlib import Path

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger


def generate_report(
    storage: BookStorage,
    checkpoint: CheckpointManager,
    logger: PipelineLogger,
    stage_storage,
    report_schema,
):
    """
    Generate report.csv from checkpoint metrics.

    Reads all page metrics from checkpoint and writes a CSV report
    with quality-focused metrics only (filtered by report_schema).

    Args:
        storage: BookStorage instance
        checkpoint: CheckpointManager instance
        logger: PipelineLogger instance
        stage_storage: ParagraphCorrectStageStorage instance
        report_schema: ParagraphCorrectPageReport schema for filtering
    """
    logger.info("Generating report.csv from checkpoint metrics")

    # Get all page metrics from checkpoint
    checkpoint_state = checkpoint.get_status()
    page_metrics = checkpoint_state.get('page_metrics', {})

    if not page_metrics:
        logger.warning("No page metrics found in checkpoint")
        return

    # Filter metrics through report schema (only quality metrics)
    report_rows = []
    for page_num_str, metrics in sorted(page_metrics.items()):
        page_num = int(page_num_str)

        try:
            # Extract only report-relevant fields
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

    # Write CSV report
    report_path = stage_storage.get_report_path(storage)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, 'w', newline='') as f:
        fieldnames = list(report_rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    logger.info(f"Report written: {report_path} ({len(report_rows)} pages)")
