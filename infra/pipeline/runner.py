import time
from typing import List, Dict, Any
from infra.pipeline.base_stage import BaseStage


def run_stage(stage: BaseStage) -> Dict[str, Any]:
    logger = stage.logger
    stage_storage = stage.stage_storage

    logger.info(
        f"Starting stage: {stage.name}",
        dependencies=stage.dependencies
    )

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

    logger.info(f"Stage complete: {stage.name}", **stats)
    logger.close()

    return stats


def run_pipeline(stages: List[BaseStage]) -> Dict[str, Any]:
    results = {}

    for stage in stages:
        stats = run_stage(stage)
        results[stage.name] = stats

    return results