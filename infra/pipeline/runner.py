from typing import List
from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import create_logger


def run_stage(
    stage: BaseStage,
    storage: BookStorage
) -> None:
    if not stage.name:
        raise ValueError(f"{stage.__class__.__name__}.name is not set")

    if not isinstance(stage.dependencies, list):
        raise ValueError(f"{stage.__class__.__name__}.dependencies must be a list")

    stage_storage = storage.stage(stage.name)

    logs_dir = stage_storage.output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = create_logger(storage.scan_id, stage.name, log_dir=logs_dir)

    try:
        logger.info(
            f"Starting stage: {stage.name}",
            dependencies=stage.dependencies
        )

        status = stage.get_status(storage, logger)
        if status["status"] == "completed":
            logger.info("Stage already complete, skipping")
            return

        logger.info("Running before() hook")
        stage.before(storage, logger)

        logger.info("Running run() hook")
        stats = stage.run(storage, logger)

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
    storage: BookStorage,
    stop_on_error: bool = True
) -> dict:
    results = {}

    print(f"\n📚 Running pipeline: {storage.scan_id}")
    print(f"   Stages: {', '.join(s.name for s in stages)}")
    print()

    for i, stage in enumerate(stages, 1):
        print(f"[{i}/{len(stages)}] Running stage: {stage.name}")

        try:
            stats = run_stage(stage, storage)
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