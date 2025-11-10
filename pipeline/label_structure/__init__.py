from typing import Dict, Any

from infra.config import Config
from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import BatchBasedStatusTracker, MultiPhaseStatusTracker

from .margin.processor import process_margin_pass
from .body.processor import process_body_pass
from .content.processor import process_content_pass
from .tools.merge import merge_all_pages
from .tools.report_generator import generate_report

from .schemas import LabelPagesPageReport


class LabelStructureStage(BaseStage):

    name = "label-structure"
    dependencies = ["ocr-pages"]

    @classmethod
    def default_kwargs(cls, **overrides):
        kwargs = {'max_retries': overrides.get('max_retries', 3)}
        if 'model' in overrides and overrides['model']:
            kwargs['model'] = overrides['model']
        if 'workers' in overrides and overrides['workers']:
            kwargs['max_workers'] = overrides['workers']
        return kwargs

    def __init__(
        self,
        storage: BookStorage,
        model: str = None,
        max_workers: int = None,
        max_retries: int = 3,
    ):
        super().__init__(storage)

        self.model = model or Config.vision_model_primary
        self.max_workers = max_workers or Config.max_workers
        self.max_retries = max_retries

        self.margin_tracker = BatchBasedStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            item_pattern="margin/page_{:04d}.json"
        )

        self.body_tracker = BatchBasedStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            item_pattern="body/page_{:04d}.json"
        )

        self.content_tracker = BatchBasedStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            item_pattern="content/page_{:04d}.json"
        )

        self.merge_tracker = BatchBasedStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            item_pattern="page_{:04d}.json"
        )

        self.status_tracker = MultiPhaseStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            phases=[
                {"name": "margin", "tracker": self.margin_tracker},
                {"name": "body", "tracker": self.body_tracker},
                {"name": "content", "tracker": self.content_tracker},
                {"name": "merge", "tracker": self.merge_tracker},
                {"name": "generate_report", "artifact": "report.csv"}
            ]
        )

    def run(self) -> Dict[str, Any]:
        """
        Run three-pass analysis + merge.

        Flow:
        1. Pass 1: Margin → output/margin/page_XXXX.json
        2. Pass 2: Body → output/body/page_XXXX.json
        3. Pass 3: Content → output/content/page_XXXX.json
        4. Merge → output/page_XXXX.json (final output)
        5. Report → output/report.csv
        """

        # Check if entire stage is complete
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        # Pass 1: Margin
        remaining_margin = self.margin_tracker.get_remaining_items()
        if remaining_margin:
            self.logger.info(f"Pass 1: Processing {len(remaining_margin)} margin observations")
            process_margin_pass(
                storage=self.storage,
                logger=self.logger,
                stage_name=self.name,
                remaining_pages=remaining_margin,
                model=self.model,
                max_workers=self.max_workers,
                max_retries=self.max_retries,
                tracker=self.margin_tracker
            )

        # Pass 2: Body (requires margin complete)
        remaining_body = self.body_tracker.get_remaining_items()
        if remaining_body:
            self.logger.info(f"Pass 2: Processing {len(remaining_body)} body observations")
            process_body_pass(
                storage=self.storage,
                logger=self.logger,
                stage_name=self.name,
                remaining_pages=remaining_body,
                model=self.model,
                max_workers=self.max_workers,
                max_retries=self.max_retries,
                tracker=self.body_tracker
            )

        # Pass 3: Content (requires margin + body complete)
        remaining_content = self.content_tracker.get_remaining_items()
        if remaining_content:
            self.logger.info(f"Pass 3: Processing {len(remaining_content)} content observations")
            process_content_pass(
                storage=self.storage,
                logger=self.logger,
                stage_name=self.name,
                remaining_pages=remaining_content,
                model=self.model,
                max_workers=self.max_workers,
                max_retries=self.max_retries,
                tracker=self.content_tracker
            )

        # Merge: Combine margin + body + content into final output
        pages_to_merge = self.merge_tracker.get_remaining_items()
        if pages_to_merge:
            self.logger.info(f"Merging {len(pages_to_merge)} pages")
            merge_all_pages(
                storage=self.storage,
                stage_name=self.name,
                logger=self.logger,
                model=self.model,
                pages=pages_to_merge
            )

        # Generate report
        report_path = self.stage_storage.output_dir / "report.csv"
        if not report_path.exists():
            generate_report(
                storage=self.storage,
                logger=self.logger,
                report_schema=LabelPagesPageReport,
                stage_name=self.name,
            )

        return {"status": "success"}
