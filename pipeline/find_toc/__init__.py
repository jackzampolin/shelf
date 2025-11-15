from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from infra.config import Config
from .schemas import PageRange, FinderResult, LevelPattern, StructureSummary

class FindTocStage(BaseStage):
    name = "find-toc"
    dependencies = ["mistral-ocr", "olm-ocr"]

    @classmethod
    def default_kwargs(cls, **overrides):
        kwargs = {}
        if 'model' in overrides and overrides['model']:
            kwargs['model'] = overrides['model']
        return kwargs

    def __init__(self, storage: BookStorage, model: str = None):
        super().__init__(storage)
        self.model = model or Config.vision_model_primary

        # Single artifact phase - use artifact_tracker
        from infra.pipeline.status import artifact_tracker

        def run_find_toc(tracker, **kwargs):
            from .agent.finder import TocFinderAgent

            agent = TocFinderAgent(
                storage=tracker.storage,
                logger=tracker.logger,
                max_iterations=15,
                verbose=True
            )
            return agent.search()

        self.status_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="find_toc",
            artifact_filename="finder_result.json",
            run_fn=run_find_toc,
        )



__all__ = [
    "FindTocStage",
    "PageRange",
    "FinderResult",
    "LevelPattern",
    "StructureSummary",
]
