"""
Report Generator

Generates report.csv from checkpoint metrics.
Filters metrics to show only quality-relevant data for label assessment.
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
        stage_storage: LabelPagesStageStorage instance
        report_schema: LabelPagesPageReport schema for filtering
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

    # Write CSV report
    report_path = stage_storage.get_report_path(storage)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, 'w', newline='') as f:
        fieldnames = list(report_rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    logger.info(f"Report written: {report_path} ({len(report_rows)} pages)")
