from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from infra.config import Config

from .schemas import PageRange, TableOfContents, ToCEntry, ExtractTocBookOutput
from . import find
from . import extract


class ExtractTocStage(BaseStage):
    name = "extract-toc"
    dependencies = ["ocr-pages"]

    # Metadata
    icon = "📑"
    short_name = "Extract ToC"
    description = "Identify and extract the table of contents from OCR output"

    @classmethod
    def default_kwargs(cls, **overrides):
        kwargs = {
            'max_iterations': 15,
            'max_find_attempts': 3,
            'verbose': False
        }
        if 'model' in overrides and overrides['model']:
            kwargs['model'] = overrides['model']
        return kwargs

    def __init__(
        self,
        storage: BookStorage,
        model: str = None,
        max_iterations: int = 15,
        max_find_attempts: int = 3,
        verbose: bool = False
    ):
        super().__init__(storage)

        self.model = model or Config.vision_model_primary
        self.max_iterations = max_iterations
        self.max_find_attempts = max_find_attempts
        self.verbose = verbose

        # Phase 1: Find ToC pages (with automatic retry)
        self.find_tracker = find.create_find_tracker(
            self.stage_storage,
            self.model,
            max_attempts=max_find_attempts
        )

        # Phase 2: Extract complete ToC (single call)
        self.extract_tracker = extract.create_extract_tracker(self.stage_storage, self.model)

        # Multi-phase tracker (simplified: find → extract)
        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.find_tracker,
                self.extract_tracker,
            ]
        )


__all__ = [
    "ExtractTocStage",
    "PageRange",
    "TableOfContents",
    "ToCEntry",
    "ExtractTocBookOutput",
]
