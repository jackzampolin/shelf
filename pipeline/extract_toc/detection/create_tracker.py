"""Create tracker for detection phase."""

from infra.pipeline.status import PhaseStatusTracker
from infra.pipeline.storage.stage_storage import StageStorage
from ..schemas import PageRange


def create_detection_tracker(stage_storage: StageStorage, model: str):
    """Create the ToC detection phase tracker."""

    # Discoverer function - loads ToC range when called
    def discover_toc_pages(phase_dir):
        # Check if find phase has run
        finder_result_path = stage_storage.output_dir / "finder_result.json"
        if not finder_result_path.exists():
            return []  # Find phase hasn't run yet

        # Load ToC range from find phase (phase 1, same stage)
        finder_result = stage_storage.load_file("finder_result.json")

        # If no ToC was found, return empty list (nothing to extract)
        if not finder_result.get("toc_found") or not finder_result.get("toc_page_range"):
            return []

        toc_range = PageRange(**finder_result["toc_page_range"])
        # Only process ToC pages, not all pages
        return list(range(toc_range.start_page, toc_range.end_page + 1))

    from .processor import process_toc_pages

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name="extract_entries",
        discoverer=discover_toc_pages,  # Load ToC pages dynamically
        validator=lambda page_num, phase_dir: (phase_dir / f"page_{page_num:04d}.json").exists(),
        run_fn=process_toc_pages,
        use_subdir=False,
        run_kwargs={
            "model": model,
            "max_workers": 10,
            "max_retries": 5,
        }
    )
