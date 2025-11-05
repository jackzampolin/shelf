import shutil
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


def clean_stage_directory(storage: BookStorage, stage_name: str):
    """
    Completely remove stage output directory and reset metrics.

    Warning: This operation cannot be undone.
    """
    stage_storage = storage.stage(stage_name)

    if stage_storage.output_dir.exists():
        shutil.rmtree(stage_storage.output_dir)
        stage_storage.output_dir.mkdir(parents=True)

    stage_storage.metrics_manager.reset()


def get_stage_instance(stage_name: str):
    try:
        if stage_name == 'tesseract':
            from pipeline.tesseract import TesseractStage
            return TesseractStage()
        elif stage_name == 'ocr':
            from pipeline.ocr import OCRStage
            return OCRStage()
        elif stage_name == 'ocr-pages':
            from pipeline.ocr_pages import OcrPagesStage
            return OcrPagesStage()
        elif stage_name == 'paragraph-correct':
            from pipeline.paragraph_correct import ParagraphCorrectStage
            return ParagraphCorrectStage()
        elif stage_name == 'label-pages':
            from pipeline.label_pages import LabelPagesStage
            return LabelPagesStage()
        elif stage_name == 'find-toc':
            from pipeline.find_toc import FindTocStage
            return FindTocStage()
        elif stage_name == 'extract-toc':
            from pipeline.extract_toc import ExtractTocStage
            return ExtractTocStage()
    except ImportError:
        return None
    return None


def get_stage_status(storage: BookStorage, stage_name: str):
    stage = get_stage_instance(stage_name)
    if stage is None:
        return None

    logger = PipelineLogger(storage.scan_id, stage_name)
    try:
        return stage.get_status(storage, logger)
    finally:
        logger.close()


def get_stage_and_status(storage: BookStorage, stage_name: str):
    stage = get_stage_instance(stage_name)
    if stage is None:
        return None, None

    logger = PipelineLogger(storage.scan_id, stage_name)
    try:
        status = stage.get_status(storage, logger)
        return stage, status
    finally:
        logger.close()
