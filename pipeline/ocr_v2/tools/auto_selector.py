"""
Automatic provider selection for OCR v2 (Phase 2b).

For high-agreement pages (agreement >= 0.95), automatically selects
the provider with highest confidence score.
"""

from typing import List

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBar

from ..providers import OCRProvider
from ..storage import OCRStageV2Storage
from ..status import OCRStageStatus
from .agreement import _load_provider_outputs


def auto_select_pages(
    storage: BookStorage,
    checkpoint: CheckpointManager,
    logger: PipelineLogger,
    ocr_storage: OCRStageV2Storage,
    providers: List[OCRProvider],
    page_numbers: List[int],
):
    """
    Auto-select best provider for high-agreement pages (Phase 2b).

    For pages with agreement >= 0.95, picks provider with highest confidence
    and writes selection to checkpoint + selection_map incrementally.

    Args:
        storage: BookStorage instance
        checkpoint: CheckpointManager instance
        logger: PipelineLogger instance
        ocr_storage: OCRStageV2Storage instance
        providers: List of OCR providers
        page_numbers: List of page numbers to process
    """
    if not page_numbers:
        return

    logger.info(f"Auto-selecting {len(page_numbers)} high-agreement pages...")
    progress = RichProgressBar(
        total=len(page_numbers), prefix="   ", width=40, unit="pages"
    )
    progress.update(0, suffix="selecting...")

    selected_count = 0
    for idx, page_num in enumerate(page_numbers):
        try:
            # Load provider outputs and metrics
            provider_outputs = _load_provider_outputs(
                storage, ocr_storage, providers, page_num
            )

            if not provider_outputs:
                logger.warning(f"Page {page_num} has no provider outputs, skipping")
                continue

            page_metrics = checkpoint.get_page_metrics(page_num) or {}
            agreement = page_metrics.get("provider_agreement", 0.0)

            # Select provider with highest confidence
            best_provider = max(
                provider_outputs.items(), key=lambda x: x[1]["confidence"]
            )[0]

            # Update checkpoint with selection
            selected_data = provider_outputs[best_provider]["data"]
            page_metrics.update({
                "selected_provider": best_provider,
                "selection_method": "automatic",
                "blocks_detected": len(selected_data.get("blocks", [])),
            })
            checkpoint.update_page_metrics(page_num, page_metrics)

            # Write to selection_map incrementally (critical for resume support)
            ocr_storage.update_selection(storage, page_num, {
                "provider": best_provider,
                "method": "automatic",
                "agreement": agreement,
                "confidence": provider_outputs[best_provider]["confidence"],
            })

            selected_count += 1
            progress.update(idx + 1, suffix=f"{selected_count}/{len(page_numbers)}")

            # Update phase periodically
            if (idx + 1) % 10 == 0 or (idx + 1) == len(page_numbers):
                checkpoint.set_phase(
                    OCRStageStatus.AUTO_SELECTING.value,
                    f"{idx + 1}/{len(page_numbers)} pages"
                )

        except Exception as e:
            logger.page_error("Failed to auto-select", page=page_num, error=str(e))

    progress.finish(f"   ✓ Auto-selected {selected_count} pages")
