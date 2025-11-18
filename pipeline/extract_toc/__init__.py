from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from infra.config import Config

from .schemas import PageRange, TableOfContents, ToCEntry, ExtractTocBookOutput
from . import detection
from . import validation
from . import finalize


class ExtractTocStage(BaseStage):

    name = "extract-toc"
    dependencies = ["find-toc", "mistral-ocr", "olm-ocr"]

    @classmethod
    def default_kwargs(cls, **overrides):
        kwargs = {
            'max_iterations': 15,
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
        verbose: bool = False
    ):
        super().__init__(storage)

        self.model = model or Config.vision_model_primary
        self.max_iterations = max_iterations
        self.verbose = verbose

        # Phase 1: Extract ToC entries from pages
        self.extract_tracker = detection.create_detection_tracker(self.stage_storage, self.model)

        # Phase 2: Validate and assemble with label-structure
        self.validate_tracker = validation.create_validation_tracker(
            self.stage_storage, self.model, self.max_iterations
        )

        # Phase 3: Apply corrections and build final ToC
        self.finalize_tracker = finalize.create_finalize_tracker(self.stage_storage)

        # Multi-phase tracker
        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.extract_tracker,
                self.validate_tracker,
                self.finalize_tracker,
            ]
        )


__all__ = [
    "ExtractTocStage",
    "PageRange",
    "TableOfContents",
    "ToCEntry",
    "ExtractTocBookOutput",
]
