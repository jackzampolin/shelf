from typing import Optional
from infra.storage.book_storage import BookStorage


class FindTocStageStorage:
    def __init__(self, stage_name: str):
        self.stage_name = stage_name

    def get_merged_page_text(self, storage: BookStorage, page_num: int) -> str:
        from pipeline.paragraph_correct.tools import get_merged_page_text
        return get_merged_page_text(storage, page_num)

    def finder_result_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "finder_result.json").exists()

    def load_finder_result(self, storage: BookStorage) -> Optional[dict]:
        if not self.finder_result_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("finder_result.json")

    def save_finder_result(self, storage: BookStorage, finder_data: dict):
        from .schemas import FinderResult
        validated = FinderResult(**finder_data)
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("finder_result.json", validated.model_dump())

    def grep_report_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "grep_report.json").exists()

    def load_grep_report(self, storage: BookStorage) -> Optional[dict]:
        if not self.grep_report_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("grep_report.json")

    def save_grep_report(self, storage: BookStorage, grep_data: dict):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("grep_report.json", grep_data)
