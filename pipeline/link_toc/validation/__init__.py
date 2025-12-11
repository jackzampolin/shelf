"""Validation phase for page coverage checking."""

from pathlib import Path
from typing import List

from infra.pipeline.status import PhaseStatusTracker
from infra.pipeline.storage.stage_storage import StageStorage

from .processor import validate_coverage


def create_tracker(stage_storage: StageStorage, model: str = None) -> PhaseStatusTracker:
    """Create the validation phase tracker."""

    def discover_items(phase_dir: Path) -> List[str]:
        """Discover if validation needs to run."""
        # Check if enriched_toc exists
        enriched_path = stage_storage.output_dir / "enriched_toc.json"
        if enriched_path.exists():
            return ["coverage_check"]
        return []

    def output_path_fn(item: str, phase_dir: Path) -> Path:
        """Output path for validation."""
        return phase_dir / "coverage_report.json"

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name="validation",
        discoverer=discover_items,
        output_path_fn=output_path_fn,
        run_fn=validate_coverage,
        use_subdir=True,
        run_kwargs={"model": model},
        description="Validate page coverage and investigate gaps",
    )


__all__ = ["create_tracker", "validate_coverage"]
