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

    def structure_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "structure.json").exists()

    def load_structure(self, storage: BookStorage) -> Optional[dict]:
        if not self.structure_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("structure.json")

    def save_structure(self, storage: BookStorage, structure_data: dict):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("structure.json", structure_data)

    def toc_unchecked_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "toc_unchecked.json").exists()

    def load_toc_unchecked(self, storage: BookStorage) -> Optional[dict]:
        if not self.toc_unchecked_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("toc_unchecked.json")

    def save_toc_unchecked(self, storage: BookStorage, toc_data: dict):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("toc_unchecked.json", toc_data)

    def toc_diff_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "toc_diff.json").exists()

    def load_toc_diff(self, storage: BookStorage) -> Optional[dict]:
        if not self.toc_diff_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("toc_diff.json")

    def save_toc_diff(self, storage: BookStorage, diff_data: dict):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("toc_diff.json", diff_data)

    def toc_final_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "toc.json").exists()

    def load_toc_final(self, storage: BookStorage) -> Optional[dict]:
        if not self.toc_final_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("toc.json")

    def save_toc_final(self, storage: BookStorage, toc_data: dict):
        from .schemas import ExtractTocBookOutput
        validated = ExtractTocBookOutput(**toc_data)
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("toc.json", validated.model_dump())

    def toc_output_exists(self, storage: BookStorage) -> bool:
        return self.toc_final_exists(storage)

    def load_toc(self, storage: BookStorage) -> Optional[dict]:
        return self.load_toc_final(storage)

    def save_toc(self, storage: BookStorage, toc_data: dict):
        self.save_toc_final(storage, toc_data)
