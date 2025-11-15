from infra.pipeline.status import PhaseStatusTracker

from ..schemas import PageRange
from .processor import process_toc_pages
from infra import Config


def extract_toc_entries(tracker: PhaseStatusTracker, **kwargs):
    max_workers = kwargs.get("max_workers", 10)
    max_retries = kwargs.get("max_retries", 5)

    # Access book storage through tracker's stage_storage
    book_storage = tracker.stage_storage.storage
    stage_storage = book_storage.stage('extract-toc')

    finder_result = book_storage.stage('find-toc').load_file("finder_result.json")
    toc_range = PageRange(**finder_result["toc_page_range"])

    # Create a batch tracker for the page processing
    from infra.pipeline.status import page_batch_tracker

    batch_tracker = page_batch_tracker(
        stage_storage=tracker.stage_storage,
        phase_name="extract_pages",
        run_fn=lambda t, **kw: process_toc_pages(
            tracker=t,
            model=Config.vision_model_primary,
            max_workers=max_workers,
            max_retries=max_retries,
        ),
        extension="json",
        use_subdir=False,
    )

    # Run batch processing
    batch_tracker.run()

    # Collect results
    page_results = []
    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        page_file = f"page_{page_num:04d}.json"
        try:
            page_data = stage_storage.load_file(page_file)
            page_results.append(page_data)
        except Exception as e:
            tracker.logger.warning(f"Could not load {page_file}: {e}")

    page_results.sort(key=lambda p: p["page_num"])

    results_data = {
        "pages": page_results,
        "toc_range": toc_range.model_dump(),
    }

    # Save to phase_dir (tracker handles directory creation)
    output_path = tracker.phase_dir / "entries.json"
    import json
    output_path.write_text(json.dumps(results_data, indent=2))
    tracker.logger.info(f"Saved entries.json ({len(page_results)} pages)")
