from datetime import datetime
from typing import Dict

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch_client import LLMResult
from infra.llm.metrics import llm_result_to_metrics

from pipeline.ocr.schemas import OCRPageOutput
from ..schemas import ParagraphCorrectPageMetrics
from ..tools.quality_metrics import calculate_similarity_metrics


def create_correction_handler(
    storage: BookStorage,
    stage_storage,
    logger: PipelineLogger,
    output_schema,
    stage_name: str,
    page_data_map: Dict[int, OCRPageOutput],
):
    stage_storage_obj = storage.stage(stage_name)

    def on_result(result: LLMResult):
        page_num = result.request.metadata['page_num']
        ocr_page = page_data_map[page_num]

        if not result.success:
            logger.error(f"Page {page_num} failed", page=page_num, error=result.error_message)
            return

        try:
            correction_data = result.parsed_json
            if correction_data is None:
                raise ValueError("parsed_json is None for successful result")

            similarity_ratio, chars_changed = calculate_similarity_metrics(
                ocr_page=ocr_page,
                correction_data=correction_data
            )

            page_output = {
                'page_number': page_num,
                'blocks': correction_data['blocks'],
                'model_used': result.request.model,
                'processing_cost': result.cost_usd,
                'timestamp': datetime.now().isoformat(),
                'total_blocks': len(correction_data['blocks']),
                'total_corrections': sum(
                    1 for block in correction_data['blocks']
                    for para in block['paragraphs']
                    if para.get('text') is not None
                ),
                'avg_confidence': sum(
                    para['confidence']
                    for block in correction_data['blocks']
                    for para in block['paragraphs']
                ) / max(1, sum(
                    len(block['paragraphs'])
                    for block in correction_data['blocks']
                ))
            }

            validated = output_schema(**page_output)

            llm_metrics = llm_result_to_metrics(
                result=result,
                page_num=page_num,
                extra_fields={
                    "total_corrections": page_output['total_corrections'],
                    "avg_confidence": page_output['avg_confidence'],
                    "text_similarity_ratio": similarity_ratio,
                    "characters_changed": chars_changed,
                }
            )

            stage_storage.save_corrected_page(
                storage=storage,
                page_num=page_num,
                data=validated.model_dump(),
                schema=output_schema,
                cost_usd=result.cost_usd or 0.0,
                metrics=llm_metrics
            )

            logger.info(f"✓ Page {page_num} corrected")

        except Exception as e:
            logger.error(f"Failed to save page {page_num}", page=page_num, error=str(e))

    return on_result
