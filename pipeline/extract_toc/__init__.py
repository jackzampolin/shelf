from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from .schemas import PageRange, TableOfContents, ToCEntry, ExtractTocBookOutput
from .detection import extract_toc_entries
from .assembly import assemble_toc


class ExtractTocStage(BaseStage):

    name = "extract-toc"
    dependencies = ["find-toc", "mistral-ocr", "olm-ocr"]

    @classmethod
    def default_kwargs(cls, **overrides):
        return {}

    def __init__(self, storage: BookStorage):
        super().__init__(storage)

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

        # Phase 1: Extract ToC entries
        entries_path = self.stage_storage.output_dir / "entries.json"
        if not entries_path.exists():
            from infra.pipeline.status import BatchBasedStatusTracker

            # Create tracker for ToC page range
            tracker = BatchBasedStatusTracker(
                storage=self.storage,
                logger=self.logger,
                stage_name='extract-toc',
                item_pattern="page_{:04d}.json",
                items=list(range(toc_range.start_page, toc_range.end_page + 1))
            )

            extract_toc_entries(tracker=tracker)

        # Phase 2: Assemble ToC
        toc_path = self.stage_storage.output_dir / "toc.json"
        if not toc_path.exists():
            assemble_toc(
                storage=self.storage,
                toc_range=toc_range,
                logger=self.logger
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
