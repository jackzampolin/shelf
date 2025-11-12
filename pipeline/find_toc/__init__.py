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

        self.status_tracker = MultiPhaseStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            phases=[
                {"name": "find_toc", "artifact": "finder_result.json"}
            ]
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        from .agent.finder import TocFinderAgent

        agent = TocFinderAgent(
            storage=self.storage,
            logger=self.logger,
            max_iterations=15,
            verbose=True
        )

        return agent.search()


__all__ = [
    "FindTocStage",
    "PageRange",
    "FinderResult",
    "LevelPattern",
    "StructureSummary",
]
