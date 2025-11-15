from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker, artifact_tracker
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

        # Phase 1: Extract entries artifact tracker
        self.extract_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="extract_entries",
            artifact_filename="entries.json",
            run_fn=extract_toc_entries,
        )

        # Phase 2: Assemble ToC artifact tracker
        self.assemble_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="assemble_toc",
            artifact_filename="toc.json",
            run_fn=assemble_toc,
        )

        # Multi-phase tracker
        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.extract_tracker,
                self.assemble_tracker,
            ]
        )



__all__ = [
    "ExtractTocStage",
    "extract_toc_entries",
    "assemble_toc",
    "PageRange",
    "TableOfContents",
    "ToCEntry",
    "ExtractTocBookOutput",
]
