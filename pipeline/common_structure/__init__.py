"""Common Structure Stage - builds unified book structure with text content.

Output structure:
    common-structure/
    ├── build_structure/
    │   └── structure_skeleton.json   # Entries without text content
    ├── polish_entries/
    │   ├── part_001.json             # Individual entry with polished text
    │   ├── part_002.json
    │   └── ...
    ├── merge/
    │   └── structure.json            # Final merged output
    ├── log.jsonl
    └── metrics.json

The parallel processing happens in phase 2 (polish_entries) where all entries
are processed concurrently via LLMBatchProcessor.
"""

from typing import Optional

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from infra.config import Config

from .schemas import CommonStructureOutput, BookMetadata, PageReference, StructureEntry, SectionText
from .phases import create_build_tracker, create_polish_tracker, create_merge_tracker


class CommonStructureStage(BaseStage):
    name = "common-structure"
    dependencies = ["link-toc", "label-structure", "ocr-pages"]

    # Metadata
    icon = "🏗️"
    short_name = "Build Structure"
    description = "Assemble unified document structure with chapter text and metadata"

    @classmethod
    def default_kwargs(cls, **overrides):
        kwargs = {'model': None, 'max_workers': 10}
        if 'model' in overrides and overrides['model']:
            kwargs['model'] = overrides['model']
        if 'max_workers' in overrides:
            kwargs['max_workers'] = overrides['max_workers']
        return kwargs

    def __init__(
        self,
        storage: BookStorage,
        model: Optional[str] = None,
        max_workers: int = 10
    ):
        super().__init__(storage)
        self.model = model or Config.vision_model_primary
        self.max_workers = max_workers

        # Phase 1: Build structure skeleton (fast, one LLM call for classification)
        self.build_tracker = create_build_tracker(self.stage_storage, self.model)

        # Phase 2: Polish entries (parallel LLM batch processing)
        self.polish_tracker = create_polish_tracker(
            self.stage_storage, self.model, self.max_workers
        )

        # Phase 3: Merge into final structure.json
        self.merge_tracker = create_merge_tracker(self.stage_storage)

        # Multi-phase tracker
        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.build_tracker,
                self.polish_tracker,
                self.merge_tracker,
            ]
        )


__all__ = [
    "CommonStructureStage",
    "CommonStructureOutput",
    "BookMetadata",
    "PageReference",
    "StructureEntry",
    "SectionText",
]
