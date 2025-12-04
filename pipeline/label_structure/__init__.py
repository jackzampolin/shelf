from infra.pipeline import BaseStage, BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from infra.config import Config

from . import mechanical
from . import unified
from . import merge
from . import gap_analysis
from . import gap_healing
from .schemas import LabelStructurePageOutput


class LabelStructureStage(BaseStage):
    name = "label-structure"
    dependencies = ["ocr-pages"]

    @classmethod
    def default_kwargs(cls, **overrides):
        return {}

    def __init__(self, storage: BookStorage):
        super().__init__(storage)

        self.model = Config.vision_model_primary
        self.max_workers = 30

        self.mechanical_tracker = mechanical.create_tracker(self.stage_storage)
        self.unified_tracker = unified.create_tracker(self.stage_storage, self.model, self.max_workers)
        self.gap_analysis_tracker = gap_analysis.create_tracker(self.stage_storage)
        self.agent_healing_tracker = gap_healing.create_agent_healing_tracker(
            self.stage_storage, self.model, self.max_workers
        )

        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.mechanical_tracker,
                self.unified_tracker,
                self.gap_analysis_tracker,
                self.agent_healing_tracker,
            ]
        )


__all__ = [
    "LabelStructureStage",
    "LabelStructurePageOutput",
]
