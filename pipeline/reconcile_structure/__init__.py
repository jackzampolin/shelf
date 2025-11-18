"""
reconcile-structure: Reconcile top-down (ToC) and bottom-up (page structure) views.

Architecture:
- Phase 1: validate_toc - Check/correct ToC entries using label-structure data
- Phase 2: link_entries - Agent search to link each ToC entry to scan page
- Phase 3: process_unlinked_headings - Identify heading pages not in ToC
- Phase 4: generate_final_structure - Create unified view of book structure

Dependencies:
- extract-toc: Provides top-down structural view (ToC entries)
- label-structure: Provides bottom-up structural view (per-page headings)

Output:
- validated_toc.json: ToC with corrections from label-structure
- linked_entries.json: ToC entries mapped to scan pages
- unlinked_headings.json: Heading pages not in ToC
- final_structure.json: Complete reconciled book structure
"""

from infra.pipeline import BaseStage, BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker, artifact_tracker
from infra.config import Config


class ReconcileStructureStage(BaseStage):
    name = "reconcile-structure"
    dependencies = ["extract-toc", "label-structure"]

    @classmethod
    def default_kwargs(cls, **overrides):
        """Default configuration for reconcile-structure stage."""
        kwargs = {
            'max_iterations': 15,  # Agent iterations per ToC entry
            'max_workers': 10,     # Parallel agent workers
            'verbose': False
        }
        if 'model' in overrides and overrides['model']:
            kwargs['model'] = overrides['model']
        return kwargs

    def __init__(
        self,
        storage: BookStorage,
        model: str = None,
        max_iterations: int = 15,
        max_workers: int = 10,
        verbose: bool = False
    ):
        super().__init__(storage)

        self.model = model or Config.vision_model_primary
        self.max_iterations = max_iterations
        self.max_workers = max_workers
        self.verbose = verbose

        # Phase 1: Validate ToC using label-structure data
        # Check extracted ToC entries against bottom-up heading analysis
        # Correct obvious errors (page numbers, OCR issues in titles, etc.)
        def run_validate_toc(tracker, **kwargs):
            from .validate_toc import validate_and_correct_toc
            return validate_and_correct_toc(tracker=tracker)

        self.validate_toc_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="validate_toc",
            artifact_filename="validated_toc.json",
            run_fn=run_validate_toc,
        )

        # Phase 2: Link ToC entries to scan pages using agents
        # Each ToC entry gets an agent that searches label-structure output
        # to find the corresponding scan page
        def run_link_entries(tracker, **kwargs):
            from .link_entries import link_all_toc_entries
            return link_all_toc_entries(
                tracker=tracker,
                model=self.model,
                max_iterations=self.max_iterations,
                max_workers=self.max_workers,
                verbose=self.verbose
            )

        self.link_entries_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="link_entries",
            artifact_filename="linked_entries.json",
            run_fn=run_link_entries,
        )

        # Phase 3: Process unlinked heading pages
        # Find heading pages from label-structure that aren't linked to ToC
        # These may indicate missing ToC entries or structure not in ToC
        def run_process_unlinked(tracker, **kwargs):
            from .process_unlinked_headings import process_unlinked_heading_pages
            return process_unlinked_heading_pages(tracker=tracker)

        self.process_unlinked_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="process_unlinked_headings",
            artifact_filename="unlinked_headings.json",
            run_fn=run_process_unlinked,
        )

        # Phase 4: Generate final structure
        # Combine validated ToC, linked entries, and unlinked headings
        # into a complete, reconciled view of the book's structure
        def run_generate_final_structure(tracker, **kwargs):
            from .generate_final_structure import generate_final_structure
            return generate_final_structure(tracker=tracker)

        self.final_structure_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="generate_final_structure",
            artifact_filename="final_structure.json",
            run_fn=run_generate_final_structure,
        )

        # Multi-phase tracker coordinates all phases
        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.validate_toc_tracker,
                self.link_entries_tracker,
                self.process_unlinked_tracker,
                self.final_structure_tracker,
            ]
        )


__all__ = [
    "ReconcileStructureStage",
]
