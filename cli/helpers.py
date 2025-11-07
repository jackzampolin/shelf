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


def get_stage_instance(storage: BookStorage, stage_name: str):
    """
    Create a stage instance initialized with storage.

    Args:
        storage: BookStorage instance for the book
        stage_name: Name of the stage to instantiate

    Returns:
        Initialized stage instance or None if stage not found
    """
    try:
        if stage_name == 'tesseract':
            from pipeline.tesseract import TesseractStage
            return TesseractStage(storage)
        elif stage_name == 'ocr-pages':
            from pipeline.ocr_pages import OcrPagesStage
            return OcrPagesStage(storage)
        elif stage_name == 'label-pages':
            from pipeline.label_pages import LabelPagesStage
            return LabelPagesStage(storage)
        elif stage_name == 'find-toc':
            from pipeline.find_toc import FindTocStage
            return FindTocStage(storage)
        elif stage_name == 'extract-toc':
            from pipeline.extract_toc import ExtractTocStage
            return ExtractTocStage(storage)
        elif stage_name == 'link-toc':
            from pipeline.link_toc import LinkTocStage
            return LinkTocStage(storage)
    except ImportError:
        return None
    return None


def get_stage_status(storage: BookStorage, stage_name: str):
    """Get status for a stage (stage already has logger)."""
    stage = get_stage_instance(storage, stage_name)
    if stage is None:
        return None

    try:
        return stage.get_status()
    finally:
        stage.logger.close()


def get_stage_and_status(storage: BookStorage, stage_name: str):
    """Get stage instance and its status (stage already has logger)."""
    stage = get_stage_instance(storage, stage_name)
    if stage is None:
        return None, None

    try:
        status = stage.get_status()
        return stage, status
    finally:
        stage.logger.close()
