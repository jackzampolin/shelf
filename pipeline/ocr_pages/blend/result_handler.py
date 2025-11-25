from infra.llm.models import LLMResult
from infra.pipeline import PhaseStatusTracker
from ..schemas.blend import BlendedOcrPageOutput


def create_result_handler(tracker: PhaseStatusTracker):
    tracker = tracker

    def on_result(result: LLMResult):
        if result.success:
            if result.parsed_json is None:
                tracker.logger.error(
                    f"✗ Blend returned None: {result.request.id}",
                    request_id=result.request.id,
                    error="LLM returned null/empty response"
                )
                return

            page_num = int(result.request.id.split("_")[1])
            markdown = result.parsed_json.get("markdown", "").strip()

            output = BlendedOcrPageOutput(
                page_num=page_num,
                markdown=markdown,
                char_count=len(markdown),
                model_used=result.model_used or "unknown",
            )

            tracker.stage_storage.save_page(
                page_num,
                output.model_dump(),
                schema=BlendedOcrPageOutput,
                subdir="blend"
            )
            
            result.record_to_metrics(
                metrics_manager=tracker.stage_storage.metrics_manager,
                key=f"{tracker.metrics_prefix}{result.request.id}",
            )

            tracker.logger.info(
                f"✓ {result.request.id}: blended {output.char_count} chars"
            )
        else:
            tracker.logger.error(
                f"✗ Blend failed: {result.request.id}",
                request_id=result.request.id,
                error_type=result.error_type,
                error=result.error_message,
                attempts=result.attempts,
                execution_time=result.execution_time_seconds,
                model=result.model_used
            )

    return on_result
