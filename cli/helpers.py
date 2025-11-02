from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


def get_stage_status(storage: BookStorage, stage_name: str):
    from pipeline.ocr import OCRStage
    from pipeline.paragraph_correct import ParagraphCorrectStage
    from pipeline.label_pages import LabelPagesStage
    from pipeline.merged import MergeStage

    stage_map = {
        'ocr': OCRStage(),
        'paragraph-correct': ParagraphCorrectStage(),
        'label-pages': LabelPagesStage(),
        'merged': MergeStage(),
    }

    if stage_name not in stage_map:
        return None

    stage = stage_map[stage_name]
    logger = PipelineLogger(storage.scan_id, stage_name)

    try:
        return stage.get_status(storage, logger)
    finally:
        logger.close()
