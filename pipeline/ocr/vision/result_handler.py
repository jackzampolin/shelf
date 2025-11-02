from typing import List

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch_client import LLMResult
from infra.llm.metrics import llm_result_to_metrics

from ..storage import OCRStageStorage
from ..providers import OCRProvider
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
            logger.page_error("Vision selection failed", page=page_num, error=result.error_message)
            return

        try:
            page_num = result.request.metadata["page_num"]
            provider_outputs = result.request.metadata["provider_outputs"]

            validated = VisionSelectionResponse(**result.parsed_json)

            provider_index = validated.selected_psm - 3
            provider_names = list(provider_outputs.keys())

            if not (0 <= provider_index < len(provider_names)):
                raise ValueError(f"Invalid PSM {validated.selected_psm}")

            selected_provider = provider_names[provider_index]
            selected_data = provider_outputs[selected_provider]["data"]

            metrics = stage_storage.metrics_manager.get(f"page_{page_num:04d}") or {}
            agreement = metrics.get("provider_agreement", 0.0)

            llm_metrics = llm_result_to_metrics(
                result=result,
                page_num=page_num,
                extra_fields={
                    "confidence": validated.confidence,
                    "reason": validated.reason,
                }
            )

            stage_storage.metrics_manager.record(
                key=f"page_{page_num:04d}",
                custom_metrics=llm_metrics,
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
            logger.page_error("Failed to process vision result", page=page_num, error=str(e))

    return on_result
