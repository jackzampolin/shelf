from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from infra.config import Config
from .orchestrator import find_all_toc_entries
from .tools.report_generator import generate_report


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

        self.status_tracker = MultiPhaseStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            phases=[
                {"name": "find_entries", "artifact": "linked_toc.json"},
                {"name": "generate_report", "artifact": "report.csv"}
            ]
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        # Phase 1: Find all ToC entries
        linked_toc_path = self.stage_storage.output_dir / "linked_toc.json"
        if not linked_toc_path.exists():
            find_all_toc_entries(
                storage=self.storage,
                logger=self.logger,
                model=self.model,
                max_iterations=self.max_iterations,
                verbose=self.verbose
            )

        # Phase 2: Generate report
        report_path = self.stage_storage.output_dir / "report.csv"
        if not report_path.exists():
            generate_report(
                storage=self.storage,
                logger=self.logger,
                stage_name=self.name
            )

        return {"status": "success"}
