from pathlib import Path
from typing import List, Optional
from PIL import Image

from infra.storage.book_storage import BookStorage


class ParagraphCorrectStageStorage:

    def __init__(self, stage_name: str):
        self.stage_name = stage_name

    def list_completed_pages(self, storage: BookStorage) -> List[int]:
        stage_storage = storage.stage(self.stage_name)
        output_pages = stage_storage.list_output_pages(extension='json')
        page_nums = [int(p.stem.split('_')[1]) for p in output_pages]
        return sorted(page_nums)

    def load_ocr_page(self, storage: BookStorage, page_num: int) -> Optional[dict]:
        from pipeline.ocr.storage import OCRStageStorage

        ocr_storage = OCRStageStorage(stage_name='ocr')
        return ocr_storage.load_selected_page(storage, page_num)

    def load_source_image(self, storage: BookStorage, page_num: int) -> Optional[Image.Image]:
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
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_page(
            page_num=page_num,
            data=data,
            schema=schema,
            cost_usd=cost_usd,
            metrics=metrics,
        )

    def get_report_path(self, storage: BookStorage) -> Path:
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.output_dir / "report.csv"

    def report_exists(self, storage: BookStorage) -> bool:
        return self.get_report_path(storage).exists()
