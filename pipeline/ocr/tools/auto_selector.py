from typing import List

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBar

from ..providers import OCRProvider
from ..storage import OCRStageStorage
from .agreement import _load_provider_outputs


def auto_select_pages(
    storage: BookStorage,
    logger: PipelineLogger,
    ocr_storage: OCRStageStorage,
    providers: List[OCRProvider],
    page_numbers: List[int],
    stage_name: str,
):
    if not page_numbers:
        return

    stage_storage = storage.stage(stage_name)

    logger.info(f"Auto-selecting {len(page_numbers)} high-agreement pages...")
    progress = RichProgressBar(
        total=len(page_numbers), prefix="   ", width=40, unit="pages"
    )
    progress.update(0, suffix="selecting...")

    selected_count = 0
    for idx, page_num in enumerate(page_numbers):
        try:
            provider_outputs = _load_provider_outputs(
                storage, ocr_storage, providers, page_num
            )

            if not provider_outputs:
                logger.warning(f"Page {page_num} has no provider outputs, skipping")
                continue

            metrics = stage_storage.metrics_manager.get(f"page_{page_num:04d}") or {}
            agreement = metrics.get("provider_agreement", 0.0)

            best_provider = max(
                provider_outputs.items(), key=lambda x: x[1]["confidence"]
            )[0]

            # Update selection_map.json (ground truth for selections)
            # No metrics needed - selection is stored in selection_map, agreement already in metrics
            ocr_storage.update_selection(storage, page_num, {
                "provider": best_provider,
                "method": "automatic",
                "agreement": agreement,
                "confidence": provider_outputs[best_provider]["confidence"],
            })

            selected_count += 1
            progress.update(idx + 1, suffix=f"{selected_count}/{len(page_numbers)}")

        except Exception as e:
            logger.error("Failed to auto-select", page=page_num, error=str(e))

    progress.finish(f"   ✓ Auto-selected {selected_count} pages")
