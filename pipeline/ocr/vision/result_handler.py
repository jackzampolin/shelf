from typing import List

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch_client import LLMResult
from infra.llm.metrics import record_llm_result

from ..storage import OCRStageStorage
from ..providers import OCRProvider
from ..constants import PSM_TO_PROVIDER
from .schemas import VisionSelectionResponse


def create_vision_handler(
    storage: BookStorage,
    ocr_storage: OCRStageStorage,
    logger: PipelineLogger,
    providers: List[OCRProvider],
    stage_name: str,
):
    stage_storage = storage.stage(stage_name)

    def on_result(result: LLMResult):
        if not result.success:
            page_num = result.request.metadata.get("page_num", "unknown")
            logger.error("Vision selection failed", page=page_num, error=result.error_message)
            return

        try:
            page_num = result.request.metadata.get("page_num")
            if page_num is None:
                logger.error("Missing page_num in vision result metadata")
                return

            provider_outputs = result.request.metadata.get("provider_outputs")
            if not provider_outputs:
                logger.error("Missing provider_outputs in vision result metadata", page=page_num)
                return

            validated = VisionSelectionResponse(**result.parsed_json)

            selected_provider = PSM_TO_PROVIDER.get(validated.selected_psm)
            if not selected_provider:
                raise ValueError(
                    f"Invalid PSM {validated.selected_psm}. "
                    f"Valid PSM values: {list(PSM_TO_PROVIDER.keys())}"
                )

            if selected_provider not in provider_outputs:
                raise ValueError(
                    f"Selected provider '{selected_provider}' not found in outputs. "
                    f"Available providers: {list(provider_outputs.keys())}"
                )

            provider_data = provider_outputs[selected_provider]
            if not isinstance(provider_data, dict) or "data" not in provider_data:
                raise ValueError(
                    f"Invalid provider output structure for '{selected_provider}'. "
                    f"Expected dict with 'data' key"
                )

            selected_data = provider_data["data"]

            key = f"page_{page_num:04d}"
            metrics = stage_storage.metrics_manager.get(key) or {}
            agreement = metrics.get("provider_agreement", 0.0)

            record_llm_result(
                metrics_manager=stage_storage.metrics_manager,
                key=key,
                result=result,
                page_num=page_num,
                extra_fields={
                    "confidence": validated.confidence,
                    "reason": validated.reason,
                },
                accumulate=True
            )

            ocr_storage.update_selection(storage, page_num, {
                "provider": selected_provider,
                "method": "vision",
                "agreement": agreement,
                "confidence": validated.confidence,
            })

            logger.info(f"✓ Page {page_num} vision-selected: {selected_provider}")

        except Exception as e:
            page_num = result.request.metadata.get("page_num", "unknown")
            logger.error(
                "Failed to process vision result",
                page=page_num,
                error=str(e),
                error_type=type(e).__name__
            )

    return on_result
