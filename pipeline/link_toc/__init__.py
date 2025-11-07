from typing import Dict, Any

from infra.config import Config
from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from pipeline.find_toc import FindTocStage
from pipeline.extract_toc import ExtractTocStage
from pipeline.label_pages import LabelPagesStage
from pipeline.ocr_pages import OcrPagesStage


class LinkTocStage(BaseStage):
    name = "link-toc"
    dependencies = ["find-toc", "extract-toc", "label-pages", "ocr-pages"]

    def __init__(
        self,
        storage: BookStorage,
        model: str = None,
        max_iterations: int = 15,
        verbose: bool = False
    ):
        super().__init__(storage)

        self.model = model or Config.text_model_expensive
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

    def before(self) -> None:
        self.check_source_exists()

        find_toc_stage = FindTocStage(self.storage)
        self.check_dependency_completed(find_toc_stage)

        extract_toc_stage = ExtractTocStage(self.storage)
        self.check_dependency_completed(extract_toc_stage)

        label_pages_stage = LabelPagesStage(self.storage)
        self.check_dependency_completed(label_pages_stage)

        ocr_pages_stage = OcrPagesStage(self.storage)
        self.check_dependency_completed(ocr_pages_stage)

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        # Phase 1: Find all ToC entries
        linked_toc_path = self.stage_storage.output_dir / "linked_toc.json"
        if not linked_toc_path.exists():
            from .orchestrator import find_all_toc_entries

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
            from .tools.report_generator import generate_report

            generate_report(
                storage=self.storage,
                logger=self.logger,
                stage_name=self.name
            )

        return {"status": "success"}
