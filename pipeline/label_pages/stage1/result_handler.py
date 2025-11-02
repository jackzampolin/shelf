from infra.llm.batch_client import LLMResult


def create_stage1_handler(storage, stage_storage, logger, stage_name):
    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']
            stage1_data = result.parsed_json

            stage_storage.save_stage1_result(
                storage=storage,
                page_num=page_num,
                stage1_data=stage1_data,
                cost_usd=result.cost_usd or 0.0,
                result=result,
            )

            logger.info(f"✓ Stage 1 complete: page {page_num}")
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Stage 1 failed: page {page_num}", error=result.error)

    return on_result
