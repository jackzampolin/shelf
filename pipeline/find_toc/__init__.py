import time
from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.config import Config

from .schemas import FinderResult
from .status import FindTocStatusTracker, FindTocStatus
from .storage import FindTocStageStorage


class FindTocStage(BaseStage):
    """
    Find ToC stage - Phase 1 of ToC extraction.

    Uses grep-informed vision agent to locate Table of Contents pages.
    Outputs finder_result.json with page range and structure notes.
    """

    name = "find-toc"
    dependencies = ["paragraph-correct", "source"]

    output_schema = FinderResult
    checkpoint_schema = None
    report_schema = None
    self_validating = True

    def __init__(self, model: str = None):
        super().__init__()
        self.model = model or Config.text_model_expensive
        self.status_tracker = FindTocStatusTracker(stage_name=self.name)
        self.stage_storage = FindTocStageStorage(stage_name=self.name)

    def get_status(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        return self.status_tracker.get_status(storage)

    def pretty_print_status(self, status: Dict[str, Any]) -> str:
        lines = []

        stage_status = status.get('status', 'unknown')
        lines.append(f"   Status: {stage_status}")

        metrics = status.get('metrics', {})
        if metrics.get('total_cost_usd', 0) > 0:
            lines.append(f"   Cost:   ${metrics['total_cost_usd']:.4f}")
        if metrics.get('total_time_seconds', 0) > 0:
            mins = metrics['total_time_seconds'] / 60
            lines.append(f"   Time:   {mins:.1f}m")

        artifacts = status.get('artifacts', {})
        if artifacts.get('finder_result_exists', False):
            finder_result = self.stage_storage.load_finder_result(storage)
            if finder_result and finder_result.get('toc_found'):
                toc_range = finder_result.get('toc_page_range')
                if toc_range:
                    lines.append(f"   Found:  pages {toc_range['start_page']}-{toc_range['end_page']}")

        return '\n'.join(lines)

    def before(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ):
        logger.info(f"Find-ToC with {self.model}")

        from pipeline.paragraph_correct import ParagraphCorrectStage
        para_correct_stage = ParagraphCorrectStage()
        para_correct_progress = para_correct_stage.get_status(storage, logger)

        if para_correct_progress['status'] != 'completed':
            raise RuntimeError(
                f"Paragraph-correct stage status is '{para_correct_progress['status']}', not 'completed'. "
                f"Run paragraph-correct stage to completion first."
            )

        logger.info(f"Paragraph-correct completed: {para_correct_progress['total_pages']} pages ready")

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:

        progress = self.get_status(storage, logger)

        if progress["status"] == FindTocStatus.COMPLETED.value:
            logger.info("Find-ToC already completed (skipping)")
            return {"status": "skipped", "reason": "already completed"}

        logger.info("Starting find-toc", model=self.model)

        start_time = time.time()

        # Run ToC finder agent
        logger.info("Running ToC finder agent")
        print("\n🤖 Find-ToC: Searching for Table of Contents")

        from .agent.finder import TocFinderAgent

        agent = TocFinderAgent(
            storage=storage,
            logger=logger,
            max_iterations=15,
            verbose=True
        )

        result = agent.search()

        # Save finder_result.json
        finder_result = {
            "toc_found": result.toc_found,
            "toc_page_range": result.toc_page_range.model_dump() if result.toc_page_range else None,
            "confidence": result.confidence,
            "search_strategy_used": result.search_strategy_used,
            "pages_checked": result.pages_checked,
            "reasoning": result.reasoning,
            "structure_notes": result.structure_notes,
        }

        self.stage_storage.save_finder_result(storage, finder_result)
        logger.info("Saved finder_result.json")

        elapsed_time = time.time() - start_time

        # Record stage runtime
        stage_storage_obj = storage.stage(self.name)
        stage_storage_obj.metrics_manager.record(
            key="stage_runtime",
            time_seconds=elapsed_time
        )

        # Get total cost from metrics
        total_cost = sum(m.get('cost_usd', 0.0) for m in stage_storage_obj.metrics_manager.get_all().values())

        # Log completion (summary already shown by agent progress display)
        if result.toc_found:
            logger.info(
                "Find-ToC complete: ToC found",
                pages=f"{result.toc_page_range.start_page}-{result.toc_page_range.end_page}",
                confidence=result.confidence,
                cost=f"${total_cost:.4f}",
                time=f"{elapsed_time:.1f}s"
            )
        else:
            logger.info(
                "Find-ToC complete: No ToC found",
                reason=result.reasoning,
                cost=f"${total_cost:.4f}",
                time=f"{elapsed_time:.1f}s"
            )

        return {
            "status": "success",
            "toc_found": result.toc_found,
            "toc_page_range": f"{result.toc_page_range.start_page}-{result.toc_page_range.end_page}" if result.toc_page_range else None,
            "cost_usd": total_cost,
            "time_seconds": elapsed_time
        }
