from infra.pipeline import BaseStage, BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from infra.config import Config

from . import find_entries, pattern, discover, merge, validation
from .schemas import (
    LinkedToCEntry, LinkedTableOfContents, LinkTocReportEntry,
    PatternAnalysis, CandidateHeading,
    EnrichedToCEntry, EnrichedTableOfContents,
    PageGap, GapInvestigation, CoverageReport
)


class LinkTocStage(BaseStage):
    name = "link-toc"
    dependencies = ["extract-toc", "label-structure", "ocr-pages"]

    # Metadata
    icon = "🔗"
    short_name = "Link ToC"
    description = "Map table of contents entries to their corresponding page numbers"
    phases = [
        {"name": "find_entries", "description": "Locate each ToC entry in page content"},
        {"name": "pattern", "description": "Analyze heading patterns to find chapter sequences"},
        {"name": "discover", "description": "Search for each entry in detected patterns"},
        {"name": "merge", "description": "Merge results into enriched ToC"},
        {"name": "validation", "description": "Validate page coverage and investigate gaps"},
    ]

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
        self.find_tracker = find_entries.create_tracker(
            self.stage_storage,
            model=self.model,
            max_iterations=self.max_iterations,
            verbose=self.verbose
        )

        # Phase 2: Pattern analysis
        self.pattern_tracker = pattern.create_tracker(self.stage_storage, model=self.model)

        # Phase 3: Discover pattern entries
        self.discover_tracker = discover.create_tracker(self.stage_storage, model=self.model)

        # Phase 4: Merge into enriched ToC
        self.merge_tracker = merge.create_tracker(self.stage_storage)

        # Phase 5: Validate page coverage
        self.validation_tracker = validation.create_tracker(self.stage_storage, model=self.model)

        # Multi-phase tracker
        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.find_tracker,
                self.pattern_tracker,
                self.discover_tracker,
                self.merge_tracker,
                self.validation_tracker,
            ]
        )


__all__ = [
    "LinkTocStage",
    "LinkedToCEntry",
    "LinkedTableOfContents",
    "LinkTocReportEntry",
]
