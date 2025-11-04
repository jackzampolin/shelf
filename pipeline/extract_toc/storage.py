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

    def bboxes_extracted_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "bboxes_extracted.json").exists()

    def load_bboxes_extracted(self, storage: BookStorage) -> Optional[dict]:
        if not self.bboxes_extracted_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("bboxes_extracted.json")

    def save_bboxes_extracted(self, storage: BookStorage, bboxes_data: dict):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("bboxes_extracted.json", bboxes_data)

    def bboxes_verified_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "bboxes_verified.json").exists()

    def load_bboxes_verified(self, storage: BookStorage) -> Optional[dict]:
        if not self.bboxes_verified_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("bboxes_verified.json")

    def save_bboxes_verified(self, storage: BookStorage, bboxes_data: dict):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("bboxes_verified.json", bboxes_data)

    def bboxes_ocr_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "bboxes_ocr.json").exists()

    def load_bboxes_ocr(self, storage: BookStorage) -> Optional[dict]:
        if not self.bboxes_ocr_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("bboxes_ocr.json")

    def save_bboxes_ocr(self, storage: BookStorage, ocr_data: dict):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("bboxes_ocr.json", ocr_data)

    def toc_assembled_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "toc_assembled.json").exists()

    def load_toc_assembled(self, storage: BookStorage) -> Optional[dict]:
        if not self.toc_assembled_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("toc_assembled.json")

    def save_toc_assembled(self, storage: BookStorage, toc_data: dict):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("toc_assembled.json", toc_data)

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

    def toc_output_exists(self, storage: BookStorage) -> bool:
        return self.toc_validated_exists(storage)

    def load_toc(self, storage: BookStorage) -> Optional[dict]:
        return self.load_toc_validated(storage)

    def save_toc(self, storage: BookStorage, toc_data: dict):
        self.save_toc_validated(storage, toc_data)
