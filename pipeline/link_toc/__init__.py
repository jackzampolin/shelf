from infra.pipeline import BaseStage, BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from infra.config import Config

from . import find_entries, pattern, evaluation, merge
from .schemas import (
    AgentResult, LinkedToCEntry, LinkedTableOfContents, LinkTocReportEntry,
    PatternAnalysis, CandidateHeading, HeadingDecision,
    EnrichedToCEntry, EnrichedTableOfContents
)


class LinkTocStage(BaseStage):
    name = "link-toc"
    dependencies = ["extract-toc", "label-structure", "ocr-pages"]

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

        # Phase 2: Pattern analysis (LLM-based)
        self.pattern_tracker = pattern.create_tracker(self.stage_storage, model=self.model)

        # Phase 3: Evaluate candidate headings (vision-based)
        self.evaluation_tracker = evaluation.create_tracker(self.stage_storage, model=self.model)

        # Phase 4: Merge into enriched ToC
        self.merge_tracker = merge.create_tracker(self.stage_storage)

        # Multi-phase tracker
        self.status_tracker = MultiPhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_trackers=[
                self.find_tracker,
                self.pattern_tracker,
                self.evaluation_tracker,
                self.merge_tracker,
            ]
        )



__all__ = [
    "LinkTocStage",
    "AgentResult",
    "LinkedToCEntry",
    "LinkedTableOfContents",
    "LinkTocReportEntry",
]
