import csv
from pathlib import Path
from typing import Optional

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from ..storage import OCRStageStorage
from ..schemas import OCRPageReport


def generate_report(
    storage: BookStorage,
    logger: PipelineLogger,
    ocr_storage: OCRStageStorage,
    report_schema,  # OCRPageReport
    stage_name: str,
) -> Optional[Path]:
    logger.info("Generating report.csv from metrics...")

    # Ground truth: Iterate over selection_map (all selected pages)
    selection_map = ocr_storage.load_selection_map(storage)

    if not selection_map:
        logger.warning("No selections to report (no pages processed)")
        return None

    stage_storage = storage.stage(stage_name)

    report_rows = []
    for page_key, selection in sorted(selection_map.items()):
        try:
            page_num = int(page_key)

            # From selection_map.json (ground truth)
            provider_name = selection.get("provider")
            selection_method = selection.get("method")
            selection_agreement = selection.get("agreement", 0.0)
            selection_confidence = selection.get("confidence", 0.0)

            # From files: Count blocks in the selected provider output
            blocks_detected = 0
            if provider_name:
                provider_data = ocr_storage.load_provider_page(storage, provider_name, page_num)
                if provider_data:
                    blocks_detected = len(provider_data.get("blocks", []))

            # From metrics: Get vision-specific data (only exists for vision-selected pages)
            metrics = stage_storage.metrics_manager.get(f"page_{page_num:04d}") or {}
            provider_agreement = metrics.get("provider_agreement", selection_agreement)
            vision_reason = metrics.get("reason") if selection_method == "vision" else None
            vision_cost = metrics.get("cost_usd") if selection_method == "vision" else None

            report_row = {
                "page_num": page_num,
                "selected_provider": provider_name,
                "selection_method": selection_method,
                "provider_agreement": provider_agreement,
                "confidence_mean": selection_confidence,
                "blocks_detected": blocks_detected,
                "vision_reason": vision_reason,
                "vision_cost_usd": vision_cost,
            }

            validated = report_schema(**report_row)
            report_rows.append(validated.model_dump())

        except Exception as e:
            logger.warning(f"Failed to extract report for page {page_key}: {e}")
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
