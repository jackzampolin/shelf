import os
import time
from typing import List
from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import create_logger


def run_stage(stage: BaseStage) -> None:
    """
    Run a stage that has already been initialized with storage.

    Args:
        stage: BaseStage instance already initialized with storage
    """
    if not stage.name:
        raise ValueError(f"{stage.__class__.__name__}.name is not set")

    if not isinstance(stage.dependencies, list):
        raise ValueError(f"{stage.__class__.__name__}.dependencies must be a list")

    # Stage already has storage and logger from __init__
    logger = stage.logger
    storage = stage.storage
    stage_storage = storage.stage(stage.name)

    try:
        logger.info(
            f"Starting stage: {stage.name}",
            dependencies=stage.dependencies
        )

        status = stage.get_status()
        if status["status"] == "completed":
            logger.info("Stage already complete, skipping")
            return

        logger.info("Running before() hook")
        stage.before()

        logger.info("Running run() hook")
        start_time = time.time()
        stats = stage.run()
        elapsed_time = time.time() - start_time

        stage_storage.metrics_manager.record(
            key="stage_runtime",
            time_seconds=elapsed_time,
            accumulate=True
        )

        logger.info(f"✅ Stage complete: {stage.name}", **stats)
        return stats

    except Exception as e:
        logger.error(f"❌ Stage failed: {stage.name}", error=str(e))
        raise

    finally:
        if logger:
            logger.close()


def run_pipeline(
    stages: List[BaseStage],
    stop_on_error: bool = True
) -> dict:
    """
    Run a pipeline of stages that have already been initialized with storage.

    Args:
        stages: List of BaseStage instances already initialized
        stop_on_error: Whether to stop on first error

    Returns:
        Dict mapping stage names to execution stats
    """
    results = {}

    # Get scan_id from first stage's storage
    scan_id = stages[0].storage.scan_id if stages else "unknown"

    print(f"\n📚 Running pipeline: {scan_id}")
    print(f"   Stages: {', '.join(s.name for s in stages)}")
    print()

    for i, stage in enumerate(stages, 1):
        print(f"[{i}/{len(stages)}] Running stage: {stage.name}")

        try:
            stats = run_stage(stage)
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