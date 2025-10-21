"""
Base Stage abstraction for pipeline stages.

Provides lifecycle hooks (before/run/after) and standardized interface.
Each stage implements its own processing logic.
"""

from typing import Dict, List, Any
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger


class BaseStage:
    """
    Base class for all pipeline stages.

    Lifecycle:
        1. before() - Pre-flight checks, input validation
        2. run() - Main processing logic (REQUIRED)
        3. after() - Post-processing, reports, output validation

    Subclasses must:
        - Set `name` class attribute
        - Set `dependencies` class attribute (list of stage names)
        - Implement `run()` method

    Subclasses may override:
        - before() for input validation
        - after() for reports/validation

    Example:
        class MergeStage(BaseStage):
            name = "merge"
            dependencies = ["ocr", "corrected", "labels"]

            def run(self, storage, checkpoint, logger):
                # Merge logic here
                return {"pages_merged": 100}

            def after(self, storage, checkpoint, logger, stats):
                # Generate report
                generate_merge_report(storage, stats, logger)
    """

    # Subclasses MUST set these
    name: str = None
    dependencies: List[str] = []

    def before(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger) -> None:
        """
        Pre-flight hook: Validate inputs, check dependencies.

        Called before run(). Use for:
        - Input validation (check required files exist)
        - Dependency verification
        - Pre-loading data into cache
        - Stage-specific setup

        Args:
            storage: BookStorage instance for this book
            checkpoint: CheckpointManager for this stage
            logger: Logger instance for this stage

        Raises:
            Exception: To abort stage execution

        Default: No-op (nothing to check)
        """
        pass

    def run(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        """
        Main processing logic: DO THE WORK.

        Subclasses MUST implement this method.

        Stage controls its own iteration strategy:
        - Page-by-page: Use checkpoint.get_remaining_pages()
        - Whole-book: Load all inputs, process together
        - Hybrid: Mix approaches as needed

        Args:
            storage: BookStorage instance for this book
            checkpoint: CheckpointManager for this stage
            logger: Logger instance for this stage

        Returns:
            Stats dictionary for logging and checkpoint metadata.
            Example: {"pages_processed": 100, "total_cost_usd": 5.23}

        Raises:
            Exception: On processing failure
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement run() method"
        )

    def after(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger,
        stats: Dict[str, Any]
    ) -> None:
        """
        Post-processing hook: Validate outputs, generate reports.

        Called after run() completes successfully. Use for:
        - Output validation (check all expected files exist)
        - Report generation (quality analysis, statistics)
        - Metadata updates
        - Cleanup

        Args:
            storage: BookStorage instance for this book
            checkpoint: CheckpointManager for this stage
            logger: Logger instance for this stage
            stats: Stats dict returned by run()

        Raises:
            Exception: To fail the stage (validation failed)

        Default: No-op (nothing to do)
        """
        pass

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"{self.__class__.__name__}(name='{self.name}', dependencies={self.dependencies})"
