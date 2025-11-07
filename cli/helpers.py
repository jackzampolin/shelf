import shutil
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.registry import get_stage_instance


def clean_stage_directory(storage: BookStorage, stage_name: str):
    stage_storage = storage.stage(stage_name)

    if stage_storage.output_dir.exists():
        shutil.rmtree(stage_storage.output_dir)
        stage_storage.output_dir.mkdir(parents=True)

    stage_storage.metrics_manager.reset()


def get_stage_status(storage: BookStorage, stage_name: str):
    try:
        stage = get_stage_instance(storage, stage_name)
        return stage.get_status()
    except ValueError:
        return None
    finally:
        if 'stage' in locals():
            stage.logger.close()


def get_stage_and_status(storage: BookStorage, stage_name: str):
    try:
        stage = get_stage_instance(storage, stage_name)
        status = stage.get_status()
        return stage, status
    except ValueError:
        return None, None
    finally:
        if 'stage' in locals():
            stage.logger.close()
