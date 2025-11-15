"""
ASPIRATIONAL VERSION - Shows what this file SHOULD look like after full refactoring.

Refactoring needed:
1. Update all phase functions to accept (tracker: PhaseStatusTracker, **kwargs) instead of (storage, logger, ...)
2. Create custom tracker for agent_healing phase (directory + file check)
3. Refactor apply_healing_decisions to handle report regeneration
4. Add chapter extraction as proper phase
5. Functions should access context via tracker.storage, tracker.logger, tracker.stage_storage
6. Functions can accept **kwargs for runtime configuration (most don't need it)

Function signature migrations needed:
- process_mechanical_extraction(tracker, **kwargs) ✓ Already correct (no kwargs needed)
- process_structural_metadata(tracker, **kwargs)   ✓ Already correct (no kwargs needed)
- process_annotations(tracker, **kwargs)           ✓ Already correct (no kwargs needed)
- merge_outputs(tracker, **kwargs)                 ✓ Already correct (no kwargs needed)
- heal_page_number_gaps(tracker, **kwargs) instead of (storage, logger)
  - No kwargs needed
- generate_report(tracker, **kwargs) instead of (storage, logger, report_schema, stage_name)
  - Gets report_schema, stage_name from tracker.stage_storage.stage_name or hardcoded
- create_clusters(tracker, **kwargs) instead of (storage, logger)
  - No kwargs needed
- heal_all_clusters(tracker, **kwargs) instead of (storage, logger, model, max_iterations, max_workers)
  - Exposes: model, max_iterations, max_workers via kwargs (for CLI override)
- apply_healing_decisions(tracker, **kwargs) instead of (storage, logger) [AND regenerate report]
  - No kwargs needed (gets report_schema/stage_name internally)
- extract_chapter_markers(tracker, **kwargs) instead of (storage, logger)
  - No kwargs needed
"""

from typing import Dict, Any, Optional
from pathlib import Path
from infra.pipeline import BaseStage, BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker, page_batch_tracker, artifact_tracker, PhaseStatusTracker
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


def healing_directory_tracker(
    stage_storage,
    phase_name: str,
    run_fn,
    run_kwargs: Optional[Dict[str, Any]] = None,
) -> PhaseStatusTracker:
    """
    Custom tracker for healing directory phase.

    Completion criteria: healing/ directory exists AND contains page_*.json files
    (not just that the directory exists, which would always be true after first run)
    """
    def discover_healing_artifacts(phase_dir: Path):
        healing_dir = phase_dir / "healing"
        if not healing_dir.exists():
            return []
        return list(healing_dir.glob("page_*.json"))

    def validate_healing_complete(item, phase_dir: Path):
        # If we discovered any files, healing has run
        # This validator is called per-item, but we only care that files exist
        return item.exists()

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name=phase_name,
        discoverer=discover_healing_artifacts,
        validator=validate_healing_complete,
        run_fn=run_fn,
        use_subdir=False,
        run_kwargs=run_kwargs,
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

        # Phase 1: Mechanical extraction (PaddleOCR → page number, header, footer)
        self.mechanical_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="mechanical",
            run_fn=process_mechanical_extraction,
            use_subdir=True,
        )

        # Phase 2: Structural metadata (LLM → page number, header, footer)
        self.structure_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="structure",
            run_fn=process_structural_metadata,
            use_subdir=True,
            run_kwargs={
                "model": self.model,
                "max_workers": self.max_workers,
            }
        )

        # Phase 3: Annotations (LLM → headings)
        self.annotations_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="annotations",
            run_fn=process_annotations,
            use_subdir=True,
            run_kwargs={
                "model": self.model,
                "max_workers": self.max_workers,
            }
        )

        # Phase 4: Merge all sources into final page files
        self.merge_tracker = page_batch_tracker(
            stage_storage=self.stage_storage,
            phase_name="merge",
            run_fn=merge_outputs,
            use_subdir=False,
        )

        # Phase 5: Simple gap healing (mechanical fixes)
        # TODO: Refactor heal_page_number_gaps to accept (tracker, **kwargs)
        #       No kwargs needed - uses tracker.storage, tracker.logger
        self.simple_gap_healing_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="simple_gap_healing",
            artifact_filename="gap_healing_simple.json",
            run_fn=heal_page_number_gaps,
        )

        # Phase 6: CSV rollup of the data
        # TODO: Refactor generate_report to accept (tracker, **kwargs)
        #       No kwargs needed - gets report_schema/stage_name from tracker.stage_storage
        self.report_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="report",
            artifact_filename="report.csv",
            run_fn=generate_report,
        )

        # Phase 7: Create issue clusters for agent dispatch
        # TODO: Refactor create_clusters to accept (tracker, **kwargs)
        #       No kwargs needed - uses tracker.storage, tracker.logger
        self.clusters_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="clusters",
            artifact_filename="clusters.json",
            run_fn=create_clusters,
        )

        # Phase 8: Run gap healing agents
        # TODO: Refactor heal_all_clusters to accept (tracker, **kwargs)
        #       Exposes model, max_iterations, max_workers via kwargs (for CLI override)
        # Uses custom tracker because completion = healing/ directory exists with page_*.json files
        self.agent_healing_tracker = healing_directory_tracker(
            stage_storage=self.stage_storage,
            phase_name="agent_healing",
            run_fn=heal_all_clusters,
            run_kwargs={
                "model": self.model,
                "max_iterations": 15,
                "max_workers": self.max_workers,
            }
        )

        # Phase 9: Apply healing decisions AND regenerate report
        # TODO: Refactor apply_healing_decisions to:
        #       1. Accept (tracker, **kwargs)
        #       2. Save healing_applied.json artifact
        #       3. Regenerate report with healed values (call generate_report internally)
        #       No kwargs needed - calls generate_report internally with correct params
        self.healing_applied_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="healing_applied",
            artifact_filename="healing_applied.json",
            run_fn=apply_healing_decisions,
        )

        # Phase 10: Extract discovered chapter markers
        # TODO: Refactor extract_chapter_markers to accept (tracker, **kwargs)
        #       No kwargs needed - uses tracker.storage, tracker.logger
        self.chapters_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="chapters_discovered",
            artifact_filename="discovered_chapters.json",
            run_fn=extract_chapter_markers,
        )

        # Create multi-phase tracker with all phases
        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.mechanical_tracker,
                self.structure_tracker,
                self.annotations_tracker,
                self.merge_tracker,
                self.simple_gap_healing_tracker,
                self.report_tracker,
                self.clusters_tracker,
                self.agent_healing_tracker,
                self.healing_applied_tracker,
                self.chapters_tracker,
            ]
        )



__all__ = [
    "LabelStructureStage",
    "LabelStructurePageOutput",
    "LabelStructurePageReport",
    "StructureExtractionResponse",
]
