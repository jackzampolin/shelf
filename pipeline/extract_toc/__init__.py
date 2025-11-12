from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from infra.config import Config
from .schemas import PageRange, TableOfContents, ToCEntry, ExtractTocBookOutput
from .detection import extract_toc_entries
from .assembly import assemble_toc


class ExtractTocStage(BaseStage):

    name = "extract-toc"
    dependencies = ["find-toc", "mistral-ocr", "olm-ocr"]

    @classmethod
    def default_kwargs(cls, **overrides):
        kwargs = {}
        if 'model' in overrides and overrides['model']:
            kwargs['model'] = overrides['model']
        return kwargs

    def __init__(self, storage: BookStorage, model: str = None):
        super().__init__(storage)
        self.model = model or Config.vision_model_primary

        self.status_tracker = MultiPhaseStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            phases=[
                {"name": "extract_entries", "artifact": "entries.json"},
                {"name": "assemble_toc", "artifact": "toc.json"}
            ]
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        finder_result = self.storage.stage('find-toc').load_file("finder_result.json")
        
        toc_range = PageRange(**finder_result["toc_page_range"])
        structure_notes_from_finder = finder_result.get("structure_notes") or {}

        global_structure_from_finder = None
        if finder_result.get("structure_summary"):
            global_structure_from_finder = finder_result["structure_summary"]

        # Phase 1: Extract ToC entries
        entries_path = self.stage_storage.output_dir / "entries.json"
        if not entries_path.exists():
            extract_toc_entries(
                storage=self.storage,
                toc_range=toc_range,
                structure_notes_from_finder=structure_notes_from_finder,
                logger=self.logger,
                global_structure_from_finder=global_structure_from_finder,
                model=self.model
            )

        # Phase 2: Assemble ToC
        toc_path = self.stage_storage.output_dir / "toc.json"
        if not toc_path.exists():
            assemble_toc(
                storage=self.storage,
                toc_range=toc_range,
                logger=self.logger,
                model=self.model
            )


        return {"status": "success"}


__all__ = [
    "ExtractTocStage",
    "extract_toc_entries",
    "assemble_toc",
    "PageRange",
    "TableOfContents",
    "ToCEntry",
    "ExtractTocBookOutput",
]
