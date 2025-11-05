from typing import Optional
from infra.storage.book_storage import BookStorage


class ExtractTocStageStorage:

    def __init__(self, stage_name: str):
        self.stage_name = stage_name

    def entries_extracted_exists(self, storage: BookStorage) -> bool:
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "entries.json").exists()

    def load_entries_extracted(self, storage: BookStorage) -> Optional[dict]:
        if not self.entries_extracted_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.load_file("entries.json")

    def save_entries_extracted(self, storage: BookStorage, entries_data: dict):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("entries.json", entries_data)

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
