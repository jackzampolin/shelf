"""
Paragraph-Correct Stage Storage Operations

Handles all file I/O for the paragraph-correct stage:
- Loading OCR inputs and source images
- Saving corrected outputs
- Listing completed pages
"""

from pathlib import Path
from typing import List, Optional
from PIL import Image

from infra.storage.book_storage import BookStorage


class ParagraphCorrectStageStorage:
    """Storage operations for paragraph-correct stage."""

    def __init__(self, stage_name: str):
        self.stage_name = stage_name

    def list_completed_pages(self, storage: BookStorage) -> List[int]:
        """
        Get list of completed page numbers by checking disk.

        Completed pages have corrected output files on disk.
        This is the ground truth for resume logic.

        Args:
            storage: BookStorage instance

        Returns:
            List of completed page numbers (sorted)
        """
        stage_storage = storage.stage(self.stage_name)
        output_pages = stage_storage.list_output_pages(extension='json')
        return sorted(output_pages)

    def load_ocr_page(self, storage: BookStorage, page_num: int) -> Optional[dict]:
        """
        Load OCR data for a page using OCR stage's selection map.

        The OCR stage stores outputs in provider subdirectories (tesseract-psm3/,
        tesseract-psm4/, etc.) and maintains a selection_map.json that indicates
        which provider's output was selected for each page.

        Args:
            storage: BookStorage instance
            page_num: Page number (1-indexed)

        Returns:
            OCR page data as dict, or None if not found
        """
        from pipeline.ocr.storage import OCRStageStorage

        ocr_storage = OCRStageStorage(stage_name='ocr')
        return ocr_storage.load_selected_page(storage, page_num)

    def load_source_image(self, storage: BookStorage, page_num: int) -> Optional[Image.Image]:
        """
        Load source page image.

        Args:
            storage: BookStorage instance
            page_num: Page number (1-indexed)

        Returns:
            PIL Image, or None if not found
        """
        source_stage = storage.stage('source')
        image_file = source_stage.output_page(page_num, extension='png')

        if not image_file.exists():
            return None

        return Image.open(image_file)

    def save_corrected_page(
        self,
        storage: BookStorage,
        page_num: int,
        data: dict,
        schema,
        cost_usd: float,
        metrics: dict
    ):
        """
        Save corrected page output with metrics.

        This calls storage.stage().save_page() which validates the data
        against the schema and atomically saves both the output and metrics.

        Args:
            storage: BookStorage instance
            page_num: Page number (1-indexed)
            data: Corrected page data (validated against schema)
            schema: Pydantic schema for validation
            cost_usd: Processing cost in USD
            metrics: Checkpoint metrics dict
        """
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_page(
            page_num=page_num,
            data=data,
            schema=schema,
            cost_usd=cost_usd,
            metrics=metrics,
        )

    def get_report_path(self, storage: BookStorage) -> Path:
        """
        Get path to report.csv file.

        Args:
            storage: BookStorage instance

        Returns:
            Path to report.csv
        """
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.output_dir / "report.csv"

    def report_exists(self, storage: BookStorage) -> bool:
        """
        Check if report.csv exists.

        Args:
            storage: BookStorage instance

        Returns:
            True if report exists, False otherwise
        """
        return self.get_report_path(storage).exists()
