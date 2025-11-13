from infra.pipeline.status import BatchBasedStatusTracker

from ..schemas import PageRange
from .processor import process_toc_pages
from infra import Config


def extract_toc_entries(
    tracker: BatchBasedStatusTracker,
    max_workers: int = 10,
    max_retries: int = 5,
):
    stage_storage = tracker.storage.stage('extract-toc')

    finder_result = tracker.storage.stage('find-toc').load_file("finder_result.json")
    toc_range = PageRange(**finder_result["toc_page_range"])

    process_toc_pages(
        tracker=tracker,
        model=Config.vision_model_primary,
        max_workers=max_workers,
        max_retries=max_retries,
    )

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

    stage_storage.save_file("entries.json", results_data)
    tracker.logger.info(f"Saved entries.json ({len(page_results)} pages)")
