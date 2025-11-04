from typing import Optional
from infra.storage.book_storage import BookStorage


class ExtractTocStageStorage:

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
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("finder_result.json", finder_data)

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

    def ocr_text_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "ocr_text.json").exists()

    def load_ocr_text(self, storage: BookStorage) -> Optional[dict]:
        if not self.ocr_text_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("ocr_text.json")

    def save_ocr_text(self, storage: BookStorage, ocr_data: dict):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("ocr_text.json", ocr_data)

    def elements_identified_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "elements_identified.json").exists()

    def load_elements_identified(self, storage: BookStorage) -> Optional[dict]:
        if not self.elements_identified_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("elements_identified.json")

    def save_elements_identified(self, storage: BookStorage, elements_data: dict):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("elements_identified.json", elements_data)

    def toc_validated_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "toc.json").exists()

    def load_toc_validated(self, storage: BookStorage) -> Optional[dict]:
        if not self.toc_validated_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("toc.json")

    def save_toc_validated(self, storage: BookStorage, toc_data: dict):
        from .schemas import ExtractTocBookOutput
        validated = ExtractTocBookOutput(**toc_data)
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("toc.json", validated.model_dump())

    def save_toc_final(self, storage: BookStorage, toc_data: dict):
        self.save_toc_validated(storage, toc_data)

    def toc_output_exists(self, storage: BookStorage) -> bool:
        return self.toc_validated_exists(storage)

    def load_toc(self, storage: BookStorage) -> Optional[dict]:
        return self.load_toc_validated(storage)

    def save_toc(self, storage: BookStorage, toc_data: dict):
        self.save_toc_validated(storage, toc_data)
