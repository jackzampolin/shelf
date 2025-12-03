import shutil
from typing import List, Optional, Dict, Any
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.registry import get_stage_instance
from infra.pipeline.status.multi_phase import MultiPhaseStatusTracker
from infra.pipeline.status.phase_tracker import PhaseStatusTracker


def clean_stage_directory(storage: BookStorage, stage_name: str):
    stage_storage = storage.stage(stage_name)

    if stage_storage.output_dir.exists():
        shutil.rmtree(stage_storage.output_dir)
        stage_storage.output_dir.mkdir(parents=True)

    stage_storage.metrics_manager.reset()


def list_stage_phases(storage: BookStorage, stage_name: str) -> List[str]:
    """List available phases for a stage."""
    stage = get_stage_instance(storage, stage_name)
    try:
        tracker = stage.status_tracker
        if isinstance(tracker, MultiPhaseStatusTracker):
            return tracker.list_phases()
        elif isinstance(tracker, PhaseStatusTracker):
            return [tracker.phase_name]
        return []
    finally:
        stage.logger.close()


def clean_stage_phase(storage: BookStorage, stage_name: str, phase_name: str) -> Dict[str, Any]:
    """Clean a specific phase within a stage."""
    stage = get_stage_instance(storage, stage_name)
    try:
        tracker = stage.status_tracker
        if isinstance(tracker, MultiPhaseStatusTracker):
            return tracker.clean_phase(phase_name)
        elif isinstance(tracker, PhaseStatusTracker):
            if tracker.phase_name == phase_name:
                return tracker.clean()
            raise ValueError(f"Phase '{phase_name}' not found. Available: [{tracker.phase_name}]")
        raise ValueError(f"Stage '{stage_name}' does not support phase cleaning")
    finally:
        stage.logger.close()


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
