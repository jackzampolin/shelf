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

        # Single-phase tracking: run finder agent
        self.status_tracker = MultiPhaseStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            phases=[
                {"name": "find_toc", "artifact": "finder_result.json"}
            ]
        )

    def before(self) -> None:
        self.logger.info(f"Find-ToC with {self.model}")
        self.check_source_exists()

        ocr_pages_stage = OcrPagesStage(self.storage)
        self.check_dependency_completed(ocr_pages_stage)

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        self.logger.info("Starting find-toc", model=self.model)
        print("\n🤖 Find-ToC: Searching for Table of Contents")

        from .agent.finder import TocFinderAgent

        agent = TocFinderAgent(
            storage=self.storage,
            logger=self.logger,
            max_iterations=15,
            verbose=True
        )

        result = agent.search()

        # Save finder result
        finder_result = FinderResult(
            toc_found=result.toc_found,
            toc_page_range=result.toc_page_range,
            confidence=result.confidence,
            search_strategy_used=result.search_strategy_used,
            pages_checked=result.pages_checked,
            reasoning=result.reasoning,
            structure_notes=result.structure_notes,
            structure_summary=result.structure_summary,
        )

        self.stage_storage.save_file("finder_result.json", finder_result.model_dump())
        self.logger.info("Saved finder_result.json")

        return {"status": "success"}
