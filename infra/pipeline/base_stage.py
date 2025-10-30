"""
Base Stage abstraction for pipeline stages.

Provides lifecycle hooks (before/get_progress/run) and standardized interface.
Each stage implements its own processing logic.

All stages follow the modern pattern:
- Implement get_progress() to track work (simple or multi-phase)
- Handle all processing (including reports) in run()
- Report generation is an explicit final phase in run()
"""

from typing import Dict, List, Any, Type, Optional
from pathlib import Path
from pydantic import BaseModel

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.schemas import BasePageMetrics


class BaseStage:
    """
    Base class for all pipeline stages.

    Lifecycle:
        1. before() - Pre-flight checks, input validation
        2. get_progress() - Calculate what work remains
        3. run() - Main processing logic, handles all phases including reports

    Subclasses must:
        - Set `name` class attribute
        - Set `dependencies` class attribute (list of stage names)
        - Implement `run()` method

    Subclasses should set:
        - `input_schema`: Pydantic model for input data from dependencies
        - `output_schema`: Pydantic model for output data written by stage
        - `checkpoint_schema`: Pydantic model for metrics tracked in checkpoint
        - `report_schema`: Quality-focused subset for CSV reports (optional)

    Subclasses may override:
        - get_progress() for custom progress tracking
        - before() for input validation

    Example (Multi-Phase Stage - OCR):
        class OCRStage(BaseStage):
            name = "ocr"
            dependencies = ["source"]
            output_schema = OCRPageOutput
            checkpoint_schema = OCRPageMetrics
            report_schema = OCRPageReport

            def get_progress(self, storage, checkpoint, logger):
                # Calculate multi-phase progress
                return {"status": ..., "remaining_pages": ..., ...}

            def run(self, storage, checkpoint, logger):
                progress = self.get_progress(storage, checkpoint, logger)
                # Phase 1: OCR extraction
                # Phase 2: Selection
                # Phase 3: Metadata extraction
                # Phase 4: Report generation
                checkpoint.set_phase("completed")
                return {"pages_processed": 100}

    Example (Simple Stage - Correction):
        class CorrectionStage(BaseStage):
            name = "corrected"
            dependencies = ["ocr"]
            output_schema = CorrectionPageOutput
            checkpoint_schema = CorrectionPageMetrics
            report_schema = CorrectionPageReport

            def run(self, storage, checkpoint, logger):
                # Simple page-by-page processing
                progress = self.get_progress(storage, checkpoint, logger)
                for page_num in progress["remaining_pages"]:
                    # Process page
                    checkpoint.mark_completed(page_num, ...)

                # Generate report as final step
                self._generate_report(storage, logger)
                return {"pages_processed": len(progress["remaining_pages"])}
    """

    # Subclasses MUST set these
    name: str = None
    dependencies: List[str] = []

    # Subclasses SHOULD set these (for validation and automatic reporting)
    input_schema: Optional[Type[BaseModel]] = None
    output_schema: Optional[Type[BaseModel]] = None
    checkpoint_schema: Type[BaseModel] = BasePageMetrics
    report_schema: Optional[Type[BaseModel]] = None  # Quality-focused subset for reports

    # Set to True for stages that manage their own completion validation
    # (e.g., OCR with multi-phase status tracking)
    self_validating: bool = False

    def get_progress(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        """
        Get detailed progress information for this stage.

        Optional hook for stages with complex multi-phase processing
        (e.g., OCR with provider selection phases).

        Use for:
        - Calculating what work remains (page-by-page, phase-by-phase)
        - Determining current status (not_started, running, completed)
        - Providing detailed progress for resume logic

        Args:
            storage: BookStorage instance for this book
            checkpoint: CheckpointManager for this stage
            logger: Logger instance for this stage

        Returns:
            Dict with progress details. Common keys:
            - "status": Current stage status (e.g., "running-ocr", "completed")
            - "total_pages": Total pages in book
            - "remaining_pages": List of incomplete page numbers
            - "metrics": Aggregate metrics (cost, time, etc.)

        Default: Returns basic checkpoint-based progress
        """
        # Default implementation: Basic checkpoint progress
        total_pages = storage.metadata.get('total_pages', 0)
        remaining = checkpoint.get_remaining_pages(total_pages, resume=True)

        return {
            "status": "completed" if len(remaining) == 0 else "in_progress",
            "total_pages": total_pages,
            "remaining_pages": remaining,
        }

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

        Modern stages handle all phases in run():
        - Page-by-page processing
        - Report generation
        - Metadata extraction
        - Checkpoint completion

        Use get_progress() to determine what work remains.

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

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"{self.__class__.__name__}(name='{self.name}', dependencies={self.dependencies})"
