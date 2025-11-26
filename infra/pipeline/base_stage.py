from typing import Dict, List, Any

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.registry import get_stage_class

class BaseStage:
    name: str = None
    dependencies: List[str] = []
    status_tracker: Any = None

    def __init__(self, storage: BookStorage):
        self.storage = storage
        self.stage_storage = storage.stage(self.name)

    @property
    def logger(self):
        """Get logger from stage_storage (single source of truth)."""
        return self.stage_storage.logger()

    @classmethod
    def default_kwargs(cls, **overrides):
        return {}

    def get_status(self) -> Dict[Any, Any]:
        if not self.status_tracker:
            raise RuntimeError(
                f"{self.__class__.__name__} must set status_tracker in __init__"
            )
        return self.status_tracker.get_status()

    def check_source_exists(self) -> None:
        source_stage = self.storage.stage("source")
        source_pages = source_stage.list_pages(extension="png")

        if len(source_pages) == 0:
            raise ValueError("No source pages found - cannot run this stage")

    def check_dependency_completed(self, dependency_stage) -> None:
        status = dependency_stage.get_status()
        stage_status = status.get('status', 'unknown')

        if stage_status != 'completed':
            raise RuntimeError(
                f"{dependency_stage.name} stage is not completed (status: {stage_status}). "
                f"Run {dependency_stage.name} stage to completion first."
            )

    def pretty_print_status(self, status: Dict[str, Any]) -> str:
        lines = []

        stage_status = status.get('status', 'unknown')
        progress = status.get('progress', {})

        lines.append(f"   Status: {stage_status}")

        # Check if this is a MultiPhaseStatusTracker (has phase breakdown)
        if 'total_phases' in progress and 'completed_phases' in progress:
            total_phases = progress['total_phases']
            completed_phase_names = progress['completed_phases']
            current_phase = progress.get('current_phase')

            lines.append(f"   Phases: {len(completed_phase_names)}/{total_phases} completed")

            if current_phase:
                lines.append(f"   Current: {current_phase}")

            # Show detailed phase breakdown
            lines.append("")
            lines.append("   Phase Details:")

            # Import here to avoid circular dependency
            from infra.pipeline.status import MultiPhaseStatusTracker

            if isinstance(self.status_tracker, MultiPhaseStatusTracker):
                for i, tracker in enumerate(self.status_tracker.phase_trackers, 1):
                    phase_name = tracker.phase_name
                    phase_status = tracker.get_status()
                    phase_progress = phase_status.get('progress', {})

                    total_items = phase_progress.get('total_items', 0)
                    completed_items = phase_progress.get('completed_items', 0)

                    is_completed = tracker.is_completed()
                    is_current = phase_name == current_phase
                    has_progress = completed_items > 0 and not is_completed

                    if is_completed:
                        symbol = '✅'
                    elif is_current or has_progress:
                        symbol = '⏳'
                    else:
                        symbol = '○'

                    if total_items > 0:
                        progress_str = f"({completed_items}/{total_items})"
                    else:
                        progress_str = ""

                    lines.append(f"   {symbol} {i:2d}. {phase_name:20s} {progress_str}")

        else:
            # Single-phase tracker (PhaseStatusTracker directly)
            remaining = progress.get('remaining_items', progress.get('remaining_pages', []))
            total = progress.get('total_items', progress.get('total_pages', 0))
            completed = progress.get('completed_items', progress.get('completed_pages', 0))

            if isinstance(remaining, list):
                remaining = len(remaining)

            if total > 0:
                lines.append(f"   Items:  {completed}/{total} ({remaining} remaining)")

        # Show metrics (cost/time) regardless of tracker type
        metrics = status.get('metrics', {})
        if metrics.get('total_cost_usd', 0) > 0:
            lines.append(f"   Cost:   ${metrics['total_cost_usd']:.4f}")
        if metrics.get('total_time_seconds', 0) > 0:
            mins = metrics['total_time_seconds'] / 60
            lines.append(f"   Time:   {mins:.1f}m")

        return '\n'.join(lines)

    def before(self) -> None:
        self.check_source_exists()

        for dep_name in self.dependencies:
            dep_class = get_stage_class(dep_name)
            dep_stage = dep_class(self.storage)
            self.check_dependency_completed(dep_stage)

    def run(self) -> Dict[str, Any]:
        """Default run implementation that delegates to status_tracker.

        Stages can override this if they need custom behavior, but most stages
        can use this default implementation.
        """
        if not self.status_tracker:
            raise RuntimeError(
                f"{self.__class__.__name__} must set status_tracker in __init__"
            )

        if self.status_tracker.is_completed():
            return {"status": "skipped", "reason": "already completed"}

        result = self.status_tracker.run()
        return result if result else {"status": "success"}
