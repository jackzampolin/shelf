from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import page_batch_tracker, MultiPhaseStatusTracker
from infra.ocr import OCRBatchProcessor
from .provider import MistralOCRProvider, OlmOCRProvider, PaddleOCRProvider
from .schemas import (
    MistralOcrPageOutput,
    ImageBBox,
    PageDimensions,
    OlmOcrPageOutput,
    OlmOcrPageMetrics,
    PaddleOcrPageOutput,
    PaddleOcrPageMetrics,
)


class OcrPagesStage(BaseStage):
    name = "ocr-pages"
    dependencies = []

    @classmethod
    def default_kwargs(cls, **overrides):
        return {
            'max_workers': overrides.get('workers', 10),
            'include_images': overrides.get('include_images', False)
        }

    def __init__(
        self,
        storage: BookStorage,
        max_workers: int = 10,
        include_images: bool = False
    ):
        super().__init__(storage)
        self.max_workers = max_workers
        self.include_images = include_images

        # Create individual phase trackers for each OCR provider
        def run_mistral(tracker, **kwargs):
            processor = OCRBatchProcessor(
                provider=MistralOCRProvider(
                    tracker.stage_storage,
                    include_images=self.include_images
                ),
                status_tracker=tracker,
                max_workers=self.max_workers,
            )
            return processor.process_batch()

        def run_olm(tracker, **kwargs):
            processor = OCRBatchProcessor(
                provider=OlmOCRProvider(tracker.stage_storage),
                status_tracker=tracker,
                max_workers=self.max_workers,
            )
            return processor.process_batch()

        def run_paddle(tracker, **kwargs):
            processor = OCRBatchProcessor(
                provider=PaddleOCRProvider(tracker.stage_storage),
                status_tracker=tracker,
                max_workers=self.max_workers,
            )
            return processor.process_batch()

        self.mistral_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="mistral",
            run_fn=run_mistral,
            extension="json",
            use_subdir=True,
        )

        self.olm_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="olm",
            run_fn=run_olm,
            extension="json",
            use_subdir=True,
        )

        self.paddle_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="paddle",
            run_fn=run_paddle,
            extension="json",
            use_subdir=True,
        )

        # Wrap in MultiPhaseStatusTracker for sequential execution
        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.mistral_tracker,
                self.olm_tracker,
                self.paddle_tracker
            ]
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return {"status": "skipped", "reason": "all phases completed"}

        # Runs mistral → olm → paddle sequentially, skipping completed phases
        return self.status_tracker.run()


__all__ = [
    "OcrPagesStage",
    "MistralOCRProvider",
    "OlmOCRProvider",
    "PaddleOCRProvider",
    "MistralOcrPageOutput",
    "ImageBBox",
    "PageDimensions",
    "OlmOcrPageOutput",
    "OlmOcrPageMetrics",
    "PaddleOcrPageOutput",
    "PaddleOcrPageMetrics",
]
