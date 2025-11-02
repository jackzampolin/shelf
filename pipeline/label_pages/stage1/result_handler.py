from infra.llm.batch_client import LLMResult
from infra.llm.metrics import llm_result_to_metrics


def create_stage1_handler(storage, stage_storage, logger, stage_name):
    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']
            stage1_data = result.parsed_json

            stage1_metrics = llm_result_to_metrics(
                result=result,
                page_num=page_num,
                extra_fields={
                    'stage': 'stage1',
                }
            )

            stage_storage.save_stage1_result(
                storage=storage,
                page_num=page_num,
                stage1_data=stage1_data,
                cost_usd=result.cost_usd or 0.0,
                metrics=stage1_metrics,
            )

            logger.info(f"✓ Stage 1 complete: page {page_num}")
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Stage 1 failed: page {page_num}", error=result.error)

    return on_result
