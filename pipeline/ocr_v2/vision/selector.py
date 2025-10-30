"""
Vision-based provider selection for OCR v2 (Phase 2c).

For low-agreement pages (agreement < 0.95), uses vision model to examine
the source image and select the best OCR provider output.
"""

from typing import List
from PIL import Image

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch_client import LLMRequest, LLMResult
from infra.llm.batch_processor import LLMBatchProcessor
from infra.utils.pdf import downsample_for_vision
from infra.config import Config

from ..providers import OCRProvider
from ..storage import OCRStageV2Storage
from ..status import OCRStageStatus
from ..tools.agreement import _load_provider_outputs
from .vision_selection_prompts import SYSTEM_PROMPT, build_user_prompt
from .vision_selection_schemas import VisionSelectionResponse


def vision_select_pages(
    storage: BookStorage,
    checkpoint: CheckpointManager,
    logger: PipelineLogger,
    ocr_storage: OCRStageV2Storage,
    providers: List[OCRProvider],
    page_numbers: List[int],
    total_pages: int,
):
    """
    Vision-based selection for low-agreement pages (Phase 2c).

    Uses vision LLM to examine source image and provider outputs,
    then selects the best provider. Writes selection incrementally
    to checkpoint + selection_map.

    Args:
        storage: BookStorage instance
        checkpoint: CheckpointManager instance
        logger: PipelineLogger instance
        ocr_storage: OCRStageV2Storage instance
        providers: List of OCR providers
        page_numbers: List of page numbers to process
        total_pages: Total pages in book (for prompt context)
    """
    if not page_numbers:
        return

    logger.info(f"Running vision selection on {len(page_numbers)} low-agreement pages...")

    # Build vision requests (metadata not needed - fetched later in after() hook)
    requests = _build_vision_requests(
        storage, ocr_storage, logger, providers, page_numbers, total_pages
    )

    if not requests:
        logger.info("No vision requests built (all pages failed to load)")
        return

    # Create batch processor
    processor = LLMBatchProcessor(
        checkpoint=checkpoint,
        logger=logger,
        model=Config.vision_model_primary,
        log_dir=storage.book_dir / ocr_storage.stage_name / "vision_logs",
        max_retries=3,
    )

    # Track selections
    selections = 0

    def handle_vision_result(result: LLMResult):
        """Handle each vision selection result - parse, validate, persist"""
        nonlocal selections

        if not result.success:
            page_num = result.request.metadata.get("page_num", "unknown")
            logger.page_error("Vision selection failed", page=page_num, error=result.error_message)
            return

        try:
            # Extract metadata
            page_num = result.request.metadata["page_num"]
            provider_outputs = result.request.metadata["provider_outputs"]

            # Parse and validate selection
            validated = VisionSelectionResponse(**result.parsed_json)

            # Map PSM to provider index
            provider_index = validated.selected_psm - 3
            provider_names = list(provider_outputs.keys())

            if not (0 <= provider_index < len(provider_names)):
                raise ValueError(f"Invalid provider index {provider_index}")

            selected_provider = provider_names[provider_index]
            selected_data = provider_outputs[selected_provider]["data"]

            # Update checkpoint with full metrics
            page_metrics = checkpoint.get_page_metrics(page_num) or {}
            agreement = page_metrics.get("provider_agreement", 0.0)

            page_metrics.update({
                "page_num": page_num,
                "selected_provider": selected_provider,
                "selection_method": "vision",
                "cost_usd": result.cost_usd,
                "confidence": validated.confidence,
                "reason": validated.reason,
                "blocks_detected": len(selected_data.get("blocks", [])),
                "processing_time_seconds": result.total_time_seconds,
                # Token tracking for progress bar display
                "usage": result.usage,
                "ttft_seconds": result.ttft_seconds,
                "execution_time_seconds": result.execution_time_seconds,
            })
            checkpoint.update_page_metrics(page_num, page_metrics)

            # Write to selection_map incrementally (critical for resume support)
            ocr_storage.update_selection(storage, page_num, {
                "provider": selected_provider,
                "method": "vision",
                "agreement": agreement,
                "confidence": validated.confidence,
            })

            selections += 1

        except Exception as e:
            page_num = result.request.metadata.get("page_num", "unknown")
            logger.page_error("Failed to process vision result", page=page_num, error=str(e))

    # Process batch with callback
    stats = processor.process_batch(
        requests=requests,
        on_result=handle_vision_result,
    )

    logger.info(f"   ✓ Vision-selected {selections} pages, ${stats['total_cost_usd']:.4f}")


def _build_vision_requests(
    storage: BookStorage,
    ocr_storage: OCRStageV2Storage,
    logger: PipelineLogger,
    providers: List[OCRProvider],
    page_numbers: List[int],
    total_pages: int,
) -> List[LLMRequest]:
    """Build LLM requests for vision-based provider selection"""
    requests = []

    for page_num in page_numbers:
        try:
            # Load provider outputs
            provider_outputs = _load_provider_outputs(
                storage, ocr_storage, providers, page_num
            )

            if len(provider_outputs) < len(providers):
                logger.warning(
                    f"Page {page_num} missing some provider outputs, skipping vision"
                )
                continue

            # Load source image
            source_file = storage.stage("source").output_page(page_num, extension="png")
            if not source_file.exists():
                logger.warning(f"Page {page_num} source image missing, skipping vision")
                continue

            # Downsample for vision model
            pil_image = Image.open(source_file)
            downsampled = downsample_for_vision(pil_image)

            # Build prompt (no metadata needed - only page context and OCR outputs)
            user_prompt = build_user_prompt(
                page_num=page_num,
                total_pages=total_pages,
                psm_outputs=provider_outputs,
            )

            # Create request with messages format
            request = LLMRequest(
                id=f"page_{page_num:04d}_vision",
                model=Config.vision_model_primary,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                images=[downsampled],
                temperature=0.0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "vision_selection",
                        "schema": VisionSelectionResponse.model_json_schema()
                    }
                },
                metadata={
                    "page_num": page_num,
                    "provider_outputs": provider_outputs,
                },
            )

            requests.append(request)

        except Exception as e:
            logger.page_error("Failed to build vision request", page=page_num, error=str(e))

    return requests
