"""Create tracker for detection phase."""

from infra.pipeline.status import PhaseStatusTracker
from infra.pipeline.storage.stage_storage import StageStorage
from ..schemas import PageRange


def create_detection_tracker(stage_storage: StageStorage, model: str):
    """Create the ToC detection phase tracker."""

    # Load ToC range from find-toc
    book_storage = stage_storage.storage
    finder_result = book_storage.stage('find-toc').load_file("finder_result.json")
    toc_range = PageRange(**finder_result["toc_page_range"])

    # Only process ToC pages, not all pages
    toc_pages = list(range(toc_range.start_page, toc_range.end_page + 1))

    from .processor import process_toc_pages

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name="extract_entries",
        discoverer=lambda phase_dir: toc_pages,  # Only ToC pages
        validator=lambda page_num, phase_dir: (phase_dir / f"page_{page_num:04d}.json").exists(),
        run_fn=process_toc_pages,
        use_subdir=False,
        run_kwargs={
            "model": model,
            "max_workers": 10,
            "max_retries": 5,
        }
    )
