from typing import Dict, Any, List, Optional

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from infra.config import LibraryConfig, load_library_config, resolve_book_config
from infra.config.legacy import Config
from .provider import (
    MistralOCRProvider,
    OlmOCRProvider,
    PaddleOCRProvider,
    get_provider,
    list_providers,
)
from .parallel import create_parallel_ocr_tracker
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
    """
    OCR Pages Stage - Extract text from scanned page images.

    Architecture:
    - Phase 1 (ocr): Run all configured OCR providers in parallel
    - Phase 2 (blend): Combine outputs into best-quality text

    Providers run concurrently for each page, with per-provider rate limiting.
    """
    name = "ocr-pages"
    dependencies = []

    # Metadata
    icon = "📷"
    short_name = "OCR Pages"
    description = "Extract text from scanned page images using vision AI models"
    phases = [
        {"name": "ocr", "description": "Extract text using multiple OCR providers in parallel"},
        {"name": "blend", "description": "Combine OCR outputs into best-quality text"},
    ]

    @classmethod
    def default_kwargs(cls, **overrides):
        return {
            'max_workers': overrides.get('workers', 10),
            'include_images': overrides.get('include_images', False),
            'ocr_providers': overrides.get('ocr_providers', None),
        }

    def __init__(
        self,
        storage: BookStorage,
        max_workers: int = 10,
        include_images: bool = False,
        ocr_providers: Optional[List[str]] = None,
        library_config: Optional[LibraryConfig] = None,
    ):
        super().__init__(storage)
        self.max_workers = max_workers
        self.include_images = include_images

        # Load config
        if library_config is None:
            try:
                library_config = load_library_config(Config.book_storage_root)
            except Exception:
                library_config = None

        # Get provider list from config or use defaults
        if ocr_providers is None:
            if library_config:
                # Get from book config (resolves to library defaults if not overridden)
                try:
                    book_config = resolve_book_config(
                        Config.book_storage_root,
                        storage.scan_id
                    )
                    ocr_providers = book_config.ocr_providers
                except Exception:
                    ocr_providers = ["mistral", "paddle"]
            else:
                ocr_providers = ["mistral", "paddle"]

        # Instantiate providers
        self.providers = self._create_providers(ocr_providers, library_config)

        # Get blend model from config
        self.blend_model = Config.vision_model_primary
        self.blend_max_workers = 10

        # Create phase trackers
        self.ocr_tracker = create_parallel_ocr_tracker(
            stage_storage=self.stage_storage,
            providers=self.providers,
            max_workers=self.max_workers,
        )

        self.blend_tracker = blend.create_tracker(
            self.stage_storage,
            model=self.blend_model,
            max_workers=self.blend_max_workers,
        )

        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.ocr_tracker,
                self.blend_tracker,
            ]
        )

    def _create_providers(
        self,
        provider_names: List[str],
        library_config: Optional[LibraryConfig],
    ) -> list:
        """Instantiate providers from names."""
        providers = []

        for name in provider_names:
            try:
                provider = get_provider(
                    name,
                    self.stage_storage,
                    config=library_config,
                    include_images=self.include_images if name == "mistral" else False,
                )
                providers.append(provider)
            except ValueError as e:
                # Provider not found - log warning but continue
                self.stage_storage.logger().warning(f"Provider '{name}' not available: {e}")

        if not providers:
            raise ValueError(
                f"No valid OCR providers found. Requested: {provider_names}. "
                f"Available: {list_providers(library_config)}"
            )

        return providers

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return {"status": "skipped", "reason": "all phases completed"}

        # Runs ocr → blend sequentially, skipping completed phases
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
