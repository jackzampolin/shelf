"""
Stage orchestration and execution.

Provides functions to run individual stages or entire pipelines with
consistent logging, error handling, and checkpoint management.
"""

from typing import List, Optional
from pathlib import Path
from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import create_logger, PipelineLogger


def run_stage(
    stage: BaseStage,
    storage: BookStorage,
    resume: bool = False
) -> dict:
    """
    Run a single stage with full lifecycle (before/run/after).

    Handles:
    - Checkpoint initialization
    - Logger creation
    - Before/run/after orchestration
    - Error handling
    - Checkpoint finalization

    Args:
        stage: Stage instance to run
        storage: BookStorage for this book
        resume: Resume from checkpoint if True

    Returns:
        Stats dict from stage.run()

    Raises:
        ValueError: If stage.name or stage.dependencies not set
        Exception: Any exception from stage execution

    Example:
        >>> storage = BookStorage("test-book")
        >>> stage = MergeStage()
        >>> stats = run_stage(stage, storage, resume=True)
        >>> print(stats)
        {'pages_merged': 100, 'total_cost_usd': 0.0}
    """
    # Validate stage configuration
    if not stage.name:
        raise ValueError(f"{stage.__class__.__name__}.name is not set")

    if not isinstance(stage.dependencies, list):
        raise ValueError(f"{stage.__class__.__name__}.dependencies must be a list")

    # Initialize infrastructure for this stage
    stage_storage = storage.stage(stage.name)
    checkpoint = stage_storage.checkpoint

    # Create logger in stage-specific logs directory
    logs_dir = stage_storage.output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = create_logger(storage.scan_id, stage.name, log_dir=logs_dir)

    try:
        # Log stage start
        logger.start_stage()
        logger.info(
            f"Starting stage: {stage.name}",
            dependencies=stage.dependencies,
            resume=resume
        )

        # Reset checkpoint if not resuming
        if not resume:
            if not checkpoint.reset(confirm=True):
                logger.info("Stage cancelled by user")
                return {}

        # Check if already complete
        status = checkpoint.get_status()
        if status.get('status') == 'completed':
            # Validate that outputs actually exist before trusting checkpoint
            metadata = storage.load_metadata()
            total_pages = metadata.get('total_pages', 0)

            if total_pages > 0:
                is_valid = checkpoint.validate_completed_status(total_pages)
                if not is_valid:
                    # Checkpoint was invalidated, log and continue processing
                    validation_info = checkpoint.get_status().get('validation', {})
                    missing_count = validation_info.get('total_missing', 0)
                    logger.warning(
                        f"Checkpoint validation failed: {missing_count} outputs missing",
                        missing_pages=validation_info.get('missing_outputs', [])
                    )
                    logger.info("Re-running stage to process missing pages")
                else:
                    print(f"   Stage already complete, running after() hook")
                    logger.info("Stage already complete (validated), skipping")
                    # Call after() hook for post-processing (e.g., analysis)
                    stage.after(storage, checkpoint, logger, status.get('metadata', {}))
                    return status.get('metadata', {})
            else:
                print(f"   Stage already complete (no total_pages), running after() hook")
                logger.info("Stage already complete, skipping")
                # Call after() hook for post-processing (e.g., analysis)
                stage.after(storage, checkpoint, logger, status.get('metadata', {}))
                return status.get('metadata', {})

        # Run lifecycle hooks
        logger.info("Running before() hook")
        stage.before(storage, checkpoint, logger)

        logger.info("Running run() hook")
        stats = stage.run(storage, checkpoint, logger)

        logger.info("Running after() hook")
        stage.after(storage, checkpoint, logger, stats)

        # Mark stage complete
        checkpoint.mark_stage_complete(metadata=stats)

        logger.info(f"✅ Stage complete: {stage.name}", **stats)
        return stats

    except Exception as e:
        # Mark stage failed
        checkpoint.mark_stage_failed(error=str(e))
        logger.error(f"❌ Stage failed: {stage.name}", error=str(e))
        raise

    finally:
        if logger:
            logger.close()


def run_pipeline(
    stages: List[BaseStage],
    storage: BookStorage,
    resume: bool = False,
    stop_on_error: bool = True
) -> dict:
    """
    Run multiple stages in sequence.

    Each stage runs with full lifecycle (before/run/after).
    Logs overall pipeline progress.

    Args:
        stages: List of stage instances to run in order
        storage: BookStorage for this book
        resume: Resume each stage from checkpoint if True
        stop_on_error: Stop pipeline on first error if True

    Returns:
        Dict mapping stage names to their stats:
        {
            "ocr": {"pages_processed": 100},
            "correction": {"pages_processed": 100, "cost_usd": 5.23},
            ...
        }

    Raises:
        Exception: First stage error if stop_on_error=True

    Example:
        >>> stages = [OCRStage(), CorrectionStage(), LabelStage(), MergeStage()]
        >>> storage = BookStorage("test-book")
        >>> results = run_pipeline(stages, storage, resume=True)
        >>> print(f"Processed {len(results)} stages")
    """
    results = {}

    print(f"\n📚 Running pipeline: {storage.scan_id}")
    print(f"   Stages: {', '.join(s.name for s in stages)}")
    print(f"   Resume: {resume}")
    print()

    for i, stage in enumerate(stages, 1):
        print(f"[{i}/{len(stages)}] Running stage: {stage.name}")

        try:
            stats = run_stage(stage, storage, resume=resume)
            results[stage.name] = stats
            print(f"✅ {stage.name} complete")

        except Exception as e:
            print(f"❌ {stage.name} failed: {e}")
            results[stage.name] = {"error": str(e)}

            if stop_on_error:
                print(f"\n⚠️  Pipeline stopped at {stage.name}")
                raise
            else:
                print(f"⚠️  Continuing to next stage...")
                continue

    print(f"\n✅ Pipeline complete: {len(results)} stages run")
    return results


def validate_dependencies(
    stage: BaseStage,
    storage: BookStorage
) -> bool:
    """
    Validate that all stage dependencies exist.

    Checks that each dependency stage has outputs.

    Args:
        stage: Stage to validate
        storage: BookStorage for this book

    Returns:
        True if all dependencies satisfied

    Raises:
        FileNotFoundError: If any dependency missing

    Example:
        >>> merge_stage = MergeStage()  # dependencies = ["ocr", "corrected", "labels"]
        >>> validate_dependencies(merge_stage, storage)
        True
    """
    for dep in stage.dependencies:
        dep_storage = storage.stage(dep)

        # Check if dependency stage has any outputs
        output_pages = dep_storage.list_output_pages()

        if not output_pages:
            raise FileNotFoundError(
                f"Stage '{stage.name}' depends on '{dep}', but '{dep}' has no outputs. "
                f"Run '{dep}' stage first."
            )

    return True
