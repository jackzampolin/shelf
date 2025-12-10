from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import page_batch_tracker, MultiPhaseStatusTracker
from infra.ocr import OCRBatchProcessor, OCRBatchConfig
from infra.config import Config
from .provider import MistralOCRProvider, OlmOCRProvider, PaddleOCRProvider
from . import blend
from .schemas import (
    MistralOcrPageOutput,
    ImageBBox,
    PageDimensions,
    OlmOcrPageOutput,
    OlmOcrPageMetrics,
    PaddleOcrPageOutput,
    PaddleOcrPageMetrics,
    BlendedOcrPageOutput,
    BlendedOcrPageMetrics,
)


class OcrPagesStage(BaseStage):
    name = "ocr-pages"
    dependencies = []

    # Metadata
    icon = "📷"
    short_name = "OCR Pages"
    description = "Extract text from scanned page images using vision AI models"

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
        self.blend_model = Config.vision_model_primary
        self.blend_max_workers = 10

        def run_mistral(tracker, **kwargs):
            processor = OCRBatchProcessor(OCRBatchConfig(
                tracker=tracker,
                provider=MistralOCRProvider(
                    tracker.stage_storage,
                    include_images=self.include_images
                ),
                max_workers=self.max_workers,
            ))
            return processor.process_batch()

        def run_olm(tracker, **kwargs):
            processor = OCRBatchProcessor(OCRBatchConfig(
                tracker=tracker,
                provider=OlmOCRProvider(tracker.stage_storage),
                max_workers=self.max_workers,
            ))
            return processor.process_batch()

        def run_paddle(tracker, **kwargs):
            processor = OCRBatchProcessor(OCRBatchConfig(
                tracker=tracker,
                provider=PaddleOCRProvider(tracker.stage_storage),
                max_workers=self.max_workers,
            ))
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

        self.blend_tracker = blend.create_tracker(
            self.stage_storage,
            model=self.blend_model,
            max_workers=self.blend_max_workers,
        )

        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.mistral_tracker,
                self.olm_tracker,
                self.paddle_tracker,
                self.blend_tracker,
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
    "BlendedOcrPageOutput",
    "BlendedOcrPageMetrics",
]
