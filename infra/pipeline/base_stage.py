"""
Base Stage abstraction for pipeline stages.

Provides lifecycle hooks (before/run/after) and standardized interface.
Each stage implements its own processing logic.
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
        2. run() - Main processing logic (REQUIRED)
        3. after() - Post-processing, reports, output validation

    Subclasses must:
        - Set `name` class attribute
        - Set `dependencies` class attribute (list of stage names)
        - Implement `run()` method

    Subclasses should set:
        - `input_schema`: Pydantic model for input data from dependencies
        - `output_schema`: Pydantic model for output data written by stage
        - `checkpoint_schema`: Pydantic model for metrics tracked in checkpoint

    Subclasses may override:
        - before() for input validation
        - after() for custom reports/validation (default generates report.csv)

    Example:
        class CorrectionStage(BaseStage):
            name = "corrected"
            dependencies = ["ocr"]

            input_schema = OCRPageOutput
            output_schema = CorrectionPageOutput
            checkpoint_schema = CorrectionPageMetrics

            def run(self, storage, checkpoint, logger):
                # Correction logic here
                return {"pages_processed": 100}

            # after() inherited - auto-generates report.csv from checkpoint
    """

    # Subclasses MUST set these
    name: str = None
    dependencies: List[str] = []

    # Subclasses SHOULD set these (for validation and automatic reporting)
    input_schema: Optional[Type[BaseModel]] = None
    output_schema: Optional[Type[BaseModel]] = None
    checkpoint_schema: Type[BaseModel] = BasePageMetrics
    report_schema: Optional[Type[BaseModel]] = None  # Quality-focused subset for reports

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

        Default: Generates report.csv from checkpoint metrics
        """
        # Default behavior: generate standard report from checkpoint
        self.generate_report(storage, logger)

    def generate_report(
        self,
        storage: BookStorage,
        logger: Optional[PipelineLogger] = None
    ) -> Optional[Path]:
        """
        Generate quality-focused report.csv from checkpoint metrics.

        Uses report_schema (if defined) to extract quality metrics only,
        or falls back to checkpoint_schema for full metrics dump.

        Report schema filters out performance metrics (tokens, timing, etc.)
        and focuses on quality metrics for LLM-based assessment.

        Args:
            storage: BookStorage instance for this book
            logger: Optional logger for info messages

        Returns:
            Path to generated report.csv, or None if no metrics or schema

        Example:
            For CorrectionStage with CorrectionPageReport schema:
            - Loads all page metrics from checkpoint
            - Extracts only report_schema fields (quality metrics)
            - Converts to CSV with columns: page_num, total_corrections, avg_confidence, ...
            - Saves to corrected/report.csv
        """
        import csv

        # Get checkpoint for this stage
        stage_storage = storage.stage(self.name)
        checkpoint = stage_storage.checkpoint

        # Get all page metrics
        all_metrics = checkpoint.get_all_metrics()

        if not all_metrics:
            if logger:
                logger.info("No metrics to report (no pages processed)")
            return None

        # Determine which schema to use for report
        schema_to_use = self.report_schema if self.report_schema else self.checkpoint_schema

        if not schema_to_use:
            if logger:
                logger.warning("No report_schema or checkpoint_schema defined, skipping report generation")
            return None

        # Extract report fields from checkpoint metrics
        try:
            report_rows = []
            for page_num, metrics_dict in sorted(all_metrics.items()):
                # Validate against checkpoint schema first
                validated_checkpoint = self.checkpoint_schema(**metrics_dict)
                checkpoint_data = validated_checkpoint.model_dump()

                # Extract only fields that exist in report schema
                if self.report_schema:
                    report_fields = self.report_schema.model_fields.keys()
                    report_row = {k: checkpoint_data[k] for k in report_fields if k in checkpoint_data}
                    # Validate against report schema
                    validated_report = self.report_schema(**report_row)
                    report_rows.append(validated_report.model_dump())
                else:
                    # Use full checkpoint data if no report schema
                    report_rows.append(checkpoint_data)

        except Exception as e:
            if logger:
                logger.error(f"Failed to generate report from metrics: {e}")
            return None

        # Write to CSV
        report_path = stage_storage.output_dir / "report.csv"

        try:
            with open(report_path, 'w', newline='') as f:
                if report_rows:
                    # Use first row to determine columns
                    fieldnames = list(report_rows[0].keys())
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(report_rows)

            if logger:
                logger.info(f"Generated report: {report_path}")

            return report_path

        except Exception as e:
            if logger:
                logger.error(f"Failed to write report: {e}")
            return None

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"{self.__class__.__name__}(name='{self.name}', dependencies={self.dependencies})"
