from typing import Dict, Any
from infra.pipeline import BaseStage, BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker, page_batch_tracker, artifact_tracker
from infra.config import Config

from .mechanical import process_mechanical_extraction
from .structure import process_structural_metadata
from .annotations import process_annotations
from .merge import merge_outputs
from .gap_healing import (
    heal_page_number_gaps,
    heal_all_clusters,
    apply_healing_decisions,
    extract_chapter_markers
)
from .gap_healing.clustering import create_clusters

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

        # Create phase trackers
        self.mechanical_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="mechanical",
            use_subdir=True
        )

        self.structure_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="structure",
            use_subdir=True
        )

        self.annotations_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="annotations",
            use_subdir=True
        )

        self.merge_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="merge",
            use_subdir=False  # Merged files go to root of stage output
        )

        # Create multi-phase tracker
        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.mechanical_tracker,
                self.structure_tracker,
                self.annotations_tracker,
                self.merge_tracker,
                artifact_tracker(self.stage_storage, "report", "report.csv"),
                artifact_tracker(self.stage_storage, "clusters", "clusters.json"),
                artifact_tracker(self.stage_storage, "agent_healing", "healing/"),
                artifact_tracker(self.stage_storage, "healing_applied", "healing_applied.json"),
                artifact_tracker(self.stage_storage, "chapters_discovered", "discovered_chapters.json"),
            ]
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return {"status": "skipped", "reason": "already completed"}

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

        # Create issue clusters for agent-based healing
        clusters_path = self.stage_storage.output_dir / "clusters.json"
        if not clusters_path.exists():
            self.logger.info("Creating issue clusters for agent dispatch")
            cluster_results = create_clusters(
                storage=self.storage,
                logger=self.logger,
            )
            self.logger.info(
                f"Created {cluster_results['total_clusters']} clusters for agent review"
            )

        # Run gap healing agents
        healing_dir = self.stage_storage.output_dir / "healing"
        if not healing_dir.exists() or not any(healing_dir.glob("page_*.json")):
            self.logger.info("Running gap healing agents")
            heal_all_clusters(
                storage=self.storage,
                logger=self.logger,
                model=self.model,
                max_iterations=15,
                max_workers=self.max_workers
            )

        # Apply healing decisions to page files
        healing_applied_path = self.stage_storage.output_dir / "healing_applied.json"
        if not healing_applied_path.exists():
            self.logger.info("Applying healing decisions to page files")
            apply_results = apply_healing_decisions(
                storage=self.storage,
                logger=self.logger,
            )

            # Mark as applied
            self.stage_storage.save_file("healing_applied.json", apply_results)

            # Regenerate report to show healed values
            self.logger.info("Regenerating report with healed values")
            generate_report(
                storage=self.storage,
                logger=self.logger,
                report_schema=LabelStructurePageReport,
                stage_name=self.name,
            )

        # Extract chapter markers
        chapters_path = self.stage_storage.output_dir / "discovered_chapters.json"
        if not chapters_path.exists():
            self.logger.info("Extracting chapter markers from healing decisions")
            extract_chapter_markers(
                storage=self.storage,
                logger=self.logger,
            )

        return {"status": "success"}


__all__ = [
    "LabelStructureStage",
    "LabelStructurePageOutput",
    "LabelStructurePageReport",
    "StructureExtractionResponse",
]
