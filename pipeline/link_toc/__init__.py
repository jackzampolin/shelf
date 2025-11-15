from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker, artifact_tracker
from infra.config import Config
from .orchestrator import find_all_toc_entries
from .tools import generate_report
from .schemas import AgentResult, LinkedToCEntry, LinkedTableOfContents, LinkTocReportEntry


class LinkTocStage(BaseStage):
    name = "link-toc"
    dependencies = ["find-toc", "extract-toc", "label-pages", "olm-ocr"]

    @classmethod
    def default_kwargs(cls, **overrides):
        kwargs = {'max_iterations': 15, 'verbose': False}
        if 'model' in overrides and overrides['model']:
            kwargs['model'] = overrides['model']
        return kwargs

    def __init__(
        self,
        storage: BookStorage,
        model: str = None,
        max_iterations: int = 15,
        verbose: bool = False
    ):
        super().__init__(storage)

        self.model = model or Config.vision_model_primary
        self.max_iterations = max_iterations
        self.verbose = verbose

        # Phase 1: Find all ToC entries
        def run_find_entries(tracker, **kwargs):
            return find_all_toc_entries(
                tracker=tracker,
                model=self.model,
                max_iterations=self.max_iterations,
                verbose=self.verbose
            )

        self.find_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="find_entries",
            artifact_filename="linked_toc.json",
            run_fn=run_find_entries,
        )

        # Phase 2: Generate report
        self.report_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="generate_report",
            artifact_filename="report.csv",
            run_fn=generate_report,
        )

        # Multi-phase tracker
        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.find_tracker,
                self.report_tracker,
            ]
        )



__all__ = [
    "LinkTocStage",
    "find_all_toc_entries",
    "generate_report",
    "AgentResult",
    "LinkedToCEntry",
    "LinkedTableOfContents",
    "LinkTocReportEntry",
]
