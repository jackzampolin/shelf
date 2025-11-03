from typing import List

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch_processor import LLMBatchProcessor, LLMBatchConfig, batch_process_with_preparation
from infra.config import Config

from ..providers import OCRProvider
from ..storage import OCRStageStorage
from .request_builder import prepare_vision_request
from .result_handler import create_vision_handler


def vision_select_pages(
    storage: BookStorage,
    logger: PipelineLogger,
    ocr_storage: OCRStageStorage,
    providers: List[OCRProvider],
    page_numbers: List[int],
    total_pages: int,
    stage_name: str,
):
    if not page_numbers:
        return

    logger.info(f"Running vision selection on {len(page_numbers)} low-agreement pages...")

    config = LLMBatchConfig(
        model=Config.vision_model_primary,
        max_workers=Config.max_workers,
        max_retries=3,
    )

    stage_storage = storage.stage(stage_name)
    log_dir = storage.book_dir / stage_name / "vision_logs"
    processor = LLMBatchProcessor(
        logger=logger,
        log_dir=log_dir,
        config=config,
        metrics_manager=stage_storage.metrics_manager,
    )

    handler = create_vision_handler(
        storage=storage,
        ocr_storage=ocr_storage,
        logger=logger,
        providers=providers,
        stage_name=stage_name,
    )

    stats = batch_process_with_preparation(
        stage_name="Vision Selection",
        pages=page_numbers,
        request_builder=prepare_vision_request,
        result_handler=handler,
        processor=processor,
        logger=logger,
        storage=storage,
        model=config.model,
        total_pages=total_pages,
        ocr_storage=ocr_storage,
        providers=providers,
    )

    # Store actual runtime for vision selection
    if stats.get("elapsed_seconds"):
        stage_storage = storage.stage(stage_name)
        stage_storage.metrics_manager.record(
            key="stage_runtime",
            time_seconds=stats["elapsed_seconds"],
            accumulate=True
        )

    logger.info(f"   ✓ Vision selection complete: ${stats['total_cost_usd']:.4f}")
