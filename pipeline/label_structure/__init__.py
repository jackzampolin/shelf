from typing import Dict, Any
from infra.pipeline import BaseStage, BookStorage, BatchBasedStatusTracker, MultiPhaseStatusTracker
from infra.config import Config

from .mechanical import process_mechanical_extraction
from .structure import process_structural_metadata
from .annotations import process_annotations
from .merge import merge_outputs
from .gap_healing import heal_page_number_gaps

from .tools import generate_report
from .schemas import (
    LabelStructurePageOutput,
    LabelStructurePageReport,
    StructureExtractionResponse,
)


class LabelStructureStage(BaseStage):
    name = "label-structure"
    dependencies = ["mistral-ocr", "olm-ocr", "paddle-ocr"]

    @classmethod
    def default_kwargs(cls, **overrides):
        return {}

    def __init__(
        self,
        storage: BookStorage,
    ):
        super().__init__(storage)

        self.model = Config.vision_model_primary
        self.max_workers = 30
        self.max_retries = 5

        self.mechanical_tracker = BatchBasedStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            item_pattern="mechanical/page_{:04d}.json"
        )

        self.structure_tracker = BatchBasedStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            item_pattern="structure/page_{:04d}.json"
        )

        self.annotations_tracker = BatchBasedStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            item_pattern="annotations/page_{:04d}.json"
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
                {"name": "mechanical", "tracker": self.mechanical_tracker},
                {"name": "structure", "tracker": self.structure_tracker},
                {"name": "annotations", "tracker": self.annotations_tracker},
                {"name": "merge", "tracker": self.merge_tracker},
                {"name": "report", "artifact": "report.csv"}
            ]
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        remaining_mechanical = self.mechanical_tracker.get_remaining_items()
        if remaining_mechanical:
            self.logger.info(f"Mechanical extraction: {len(remaining_mechanical)} pages")
            process_mechanical_extraction(
                tracker=self.mechanical_tracker,
            )

        remaining_structure = self.structure_tracker.get_remaining_items()
        if remaining_structure:
            self.logger.info(f"Structural metadata: {len(remaining_structure)} pages")
            process_structural_metadata(
                tracker=self.structure_tracker,
                model=self.model,
                max_workers=self.max_workers,
                max_retries=self.max_retries,
            )

        remaining_annotations = self.annotations_tracker.get_remaining_items()
        if remaining_annotations:
            self.logger.info(f"Content annotations: {len(remaining_annotations)} pages")
            process_annotations(
                tracker=self.annotations_tracker,
                model=self.model,
                max_workers=self.max_workers,
                max_retries=self.max_retries,
            )

        remaining_merge = self.merge_tracker.get_remaining_items()
        if remaining_merge:
            self.logger.info(f"Merging outputs: {len(remaining_merge)} pages")
            merge_outputs(
                tracker=self.merge_tracker,
            )

        # Gap healing: Heal trivial single-page gaps and OCR errors
        self.logger.info("Running gap healing")
        gap_results = heal_page_number_gaps(
            storage=self.storage,
            logger=self.logger,
        )
        self.logger.info(
            f"Gap healing: {gap_results['total_healed']} pages healed, "
            f"{gap_results['complex_gaps']} complex gaps remain"
        )

        report_path = self.stage_storage.output_dir / "report.csv"
        if not report_path.exists():
            self.logger.info("Generating report")
            generate_report(
                storage=self.storage,
                logger=self.logger,
                report_schema=LabelStructurePageReport,
                stage_name=self.name,
            )

        return {"status": "success"}


__all__ = [
    "LabelStructureStage",
    "LabelStructurePageOutput",
    "LabelStructurePageReport",
    "StructureExtractionResponse",
]
