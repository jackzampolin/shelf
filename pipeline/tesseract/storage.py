from typing import Optional, Dict, Any
from infra.storage.book_storage import BookStorage


class TesseractStageStorage:
    def __init__(self, stage_name: str = "tesseract"):
        self.stage_name = stage_name

    def load_page(
        self,
        storage: BookStorage,
        page_num: int
    ) -> Optional[Dict[str, Any]]:
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_page(page_num)

    def page_exists(
        self,
        storage: BookStorage,
        page_num: int
    ) -> bool:
        stage_storage = storage.stage(self.stage_name)
        page_file = stage_storage.output_page(page_num, extension="json")
        return page_file.exists()
