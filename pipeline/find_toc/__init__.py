from typing import Dict, Any

from infra.config import Config
from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from pipeline.ocr_pages import OcrPagesStage

from .schemas import FinderResult


class FindTocStage(BaseStage):

    name = "find-toc"
    dependencies = ["source", "ocr-pages"]

    output_schema = FinderResult
    checkpoint_schema = None
    report_schema = None
    self_validating = True

    def __init__(self, storage: BookStorage, model: str = None):
        super().__init__(storage)
        self.model = model or Config.text_model_expensive

        self.status_tracker = MultiPhaseStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            phases=[
                {"name": "find_toc", "artifact": "finder_result.json"}
            ]
        )

    def before(self) -> None:
        self.check_source_exists()

        ocr_pages_stage = OcrPagesStage(self.storage)
        self.check_dependency_completed(ocr_pages_stage)

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

        # Agent persists finder_result.json directly
        agent.search()

        return {"status": "success"}
