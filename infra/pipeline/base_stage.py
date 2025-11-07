import os
from typing import Dict, List, Any, Optional

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger, create_logger


class BaseStage:
    name: str = None
    dependencies: List[str] = []
    status_tracker: Optional[Any] = None

    def __init__(self, storage: BookStorage):
        """
        Initialize stage with storage and create logger.

        Args:
            storage: BookStorage instance for this book
        """
        self.storage = storage
        self.stage_storage = storage.stage(self.name)

        # Create logger based on stage name and storage
        logs_dir = self.stage_storage.output_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Check DEBUG environment variable for log level
        log_level = "DEBUG" if os.environ.get("DEBUG", "").lower() in ("true", "1") else "INFO"
        self.logger = create_logger(storage.scan_id, self.name, log_dir=logs_dir, level=log_level)

    def get_status(self) -> Dict[Any, Any]:
        """Get status of this stage."""
        if self.status_tracker:
            return self.status_tracker.get_status()

        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_status() method or set status_tracker"
        )

    def check_source_exists(self) -> None:
        """
        Check if source pages exist. Raises ValueError if not.

        Raises:
            ValueError: If no source pages found
        """
        source_stage = self.storage.stage("source")
        source_pages = source_stage.list_output_pages(extension="png")

        if len(source_pages) == 0:
            raise ValueError("No source pages found - cannot run this stage")

    def check_dependency_completed(self, dependency_stage) -> None:
        """
        Check if a dependency stage is completed. Raises RuntimeError if not.

        Args:
            dependency_stage: Instance of the dependency stage to check

        Raises:
            RuntimeError: If dependency stage is not completed
        """
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
        remaining = progress.get('remaining_items', progress.get('remaining_pages', []))
        total = progress.get('total_items', progress.get('total_pages', 0))
        completed = progress.get('completed_items', progress.get('completed_pages', 0))

        if isinstance(remaining, list):
            remaining = len(remaining)

        lines.append(f"   Status: {stage_status}")

        if total > 0:
            lines.append(f"   Items:  {completed}/{total} ({remaining} remaining)")

        metrics = status.get('metrics', {})
        if metrics.get('total_cost_usd', 0) > 0:
            lines.append(f"   Cost:   ${metrics['total_cost_usd']:.4f}")
        if metrics.get('total_time_seconds', 0) > 0:
            mins = metrics['total_time_seconds'] / 60
            lines.append(f"   Time:   {mins:.1f}m")

        return '\n'.join(lines)

    def before(self) -> None:
        """
        Pre-execution hook to check dependencies.

        Stages should override this to check that dependency stages are completed.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement before() method: check the dependancy stage(s) status is complete"
        )

    def run(self) -> Dict[str, Any]:
        """
        Main stage execution logic.

        Stages should override this to implement their core functionality.
        Returns dict with execution stats (status, pages_processed, cost_usd, etc).
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement run() method: the thing that this stage does"
        )
