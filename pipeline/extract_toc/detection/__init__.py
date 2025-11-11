"""
Detection: Direct ToC Entry Extraction

Vision model extracts complete ToC entries (title + page number + hierarchy) in a single pass.
Loads OCR text directly from olm-ocr stage (no intermediate storage needed).
"""

from typing import Dict

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.config import Config

from ..schemas import PageRange
from .batch.processor import process_toc_pages


def extract_toc_entries(
    storage: BookStorage,
    toc_range: PageRange,
    structure_notes_from_finder: Dict[int, str],
    logger: PipelineLogger,
    global_structure_from_finder: dict = None,
    model: str = None
):
    """Extract ToC entries from pages using batch processor.

    Args:
        storage: BookStorage
        toc_range: Range of ToC pages
        structure_notes_from_finder: Per-page structure observations
        logger: Pipeline logger
        global_structure_from_finder: Global structure summary
        model: Model to use (default: Config.vision_model_primary)
    """
    model = model or Config.vision_model_primary
    stage_storage_obj = storage.stage('extract-toc')

    # Process all ToC pages
    results_data = process_toc_pages(
        storage=storage,
        logger=logger,
        toc_range=toc_range,
        structure_notes_from_finder=structure_notes_from_finder,
        global_structure_from_finder=global_structure_from_finder,
        model=model
    )

    # Save entries.json
    stage_storage_obj.save_file("entries.json", results_data)
    logger.info(f"Saved entries.json ({len(results_data['pages'])} pages)")

    # Metrics automatically recorded by LLMBatchProcessor
