import shutil
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


def clean_stage_directory(storage: BookStorage, stage_name: str):
    stage_storage = storage.stage(stage_name)

    if stage_storage.output_dir.exists():
        for item in stage_storage.output_dir.iterdir():
            if item.name == '.gitkeep':
                continue
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

    stage_storage.metrics_manager.reset()


def get_stage_instance(stage_name: str):
    """Get stage instance for given stage name."""
    try:
        if stage_name == 'ocr':
            from pipeline.ocr import OCRStage
            return OCRStage()
        elif stage_name == 'paragraph-correct':
            from pipeline.paragraph_correct import ParagraphCorrectStage
            return ParagraphCorrectStage()
        elif stage_name == 'label-pages':
            from pipeline.label_pages import LabelPagesStage
            return LabelPagesStage()
        elif stage_name == 'merged':
            from pipeline.merged import MergeStage
            return MergeStage()
    except ImportError:
        return None
    return None


def get_stage_status(storage: BookStorage, stage_name: str):
    """Get status dict for given stage."""
    stage = get_stage_instance(stage_name)
    if stage is None:
        return None

    logger = PipelineLogger(storage.scan_id, stage_name)
    try:
        return stage.get_status(storage, logger)
    finally:
        logger.close()


def get_stage_and_status(storage: BookStorage, stage_name: str):
    """Get both stage instance and status dict for given stage."""
    stage = get_stage_instance(stage_name)
    if stage is None:
        return None, None

    logger = PipelineLogger(storage.scan_id, stage_name)
    try:
        status = stage.get_status(storage, logger)
        return stage, status
    finally:
        logger.close()
