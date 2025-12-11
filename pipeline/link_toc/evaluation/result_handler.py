import json

from infra.llm.models import LLMResult
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.storage.stage_storage import StageStorage

from ..schemas import HeadingDecision


def create_evaluation_handler(
    stage_storage: StageStorage,
    logger: PipelineLogger,
    candidates_by_index: dict,
    metrics_prefix: str = "evaluation_",
):
    def on_result(result: LLMResult):
        if result.success:
            # Extract index from request ID (e.g., "heading_0005" -> 5)
            candidate_idx = int(result.request.id.split('_')[1])
            candidate = candidates_by_index.get(candidate_idx, {})
            page_num = candidate.get("scan_page")

            try:
                response_data = json.loads(result.response)

                include = response_data.get("include", False)

                if include:
                    decision = HeadingDecision(
                        scan_page=page_num,
                        heading_text=candidate.get("heading_text", ""),
                        include=True,
                        title=response_data.get("title", candidate.get("heading_text", "")),
                        level=response_data.get("level", candidate.get("heading_level", 1)),
                        entry_number=response_data.get("entry_number"),
                        reasoning=response_data.get("reasoning", "")
                    )
                else:
                    decision = HeadingDecision(
                        scan_page=page_num,
                        heading_text=candidate.get("heading_text", ""),
                        include=False,
                        reasoning=response_data.get("reasoning", "")
                    )

                stage_storage.save_file(
                    f"evaluation/{result.request.id}.json",
                    decision.model_dump()
                )

                result.record_to_metrics(
                    metrics_manager=stage_storage.metrics_manager,
                    key=f"{metrics_prefix}{result.request.id}",
                    extra_fields={'include': include}
                )

                status = "included" if include else "excluded"
                logger.debug(f"  {result.request.id}: {status}")

            except Exception as e:
                logger.error(
                    f"Failed to parse evaluation result for candidate {candidate_idx}",
                    error=str(e)
                )
        else:
            logger.error(
                f"Evaluation failed for {result.request.id}",
                error_type=result.error_type,
                error=result.error_message
            )

    return on_result
