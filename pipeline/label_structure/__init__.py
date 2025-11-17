from infra.pipeline import BaseStage, BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from infra.config import Config

from . import mechanical
from . import structure
from . import annotations
from . import merge
from . import gap_healing
from .schemas import (
    LabelStructurePageOutput,
    LabelStructurePageReport,
    StructureExtractionResponse,
)


class LabelStructureStage(BaseStage):
    name = "label-structure"
    dependencies = ["mistral-ocr", "olm-ocr", "paddle-ocr"]

    @classmethod
    def default_kwargs(cls, **overrides):
        return {}

    def __init__(
        self,
        storage: BookStorage,
    ):
        super().__init__(storage)

        self.model = Config.vision_model_primary
        self.max_workers = 30
        self.max_retries = 5

        # Phase 1: Mechanical Extraction
        self.mechanical_tracker = mechanical.create_tracker(self.stage_storage)

        # Phase 2: Structure Extraction
        self.structure_tracker = structure.create_tracker(self.stage_storage, self.model, self.max_workers)

        # Phase 3: Annotations Extraction
        self.annotations_tracker = annotations.create_tracker(self.stage_storage, self.model, self.max_workers)

        # Phase 4: Simple Gap Healing
        self.simple_gap_healing_tracker = gap_healing.create_simple_gap_healing_tracker(self.stage_storage)

        # Phase 5: Clusters Gap Healing
        self.clusters_tracker = gap_healing.create_clusters_tracker(self.stage_storage)

        # Phase 6: Agent Healing
        self.agent_healing_tracker = gap_healing.create_agent_healing_tracker(
            self.stage_storage, self.model, self.max_workers
        )

        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.mechanical_tracker,
                self.structure_tracker,
                self.annotations_tracker,
                self.simple_gap_healing_tracker,
                self.clusters_tracker,
                self.agent_healing_tracker,
            ]
        )


__all__ = [
    "LabelStructureStage",
    "LabelStructurePageOutput",
    "LabelStructurePageReport",
    "StructureExtractionResponse",
]
