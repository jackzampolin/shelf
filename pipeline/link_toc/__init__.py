import time
from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from .schemas import LinkedTableOfContents
from .status import LinkTocStatusTracker, LinkTocStatus
from .storage import LinkTocStageStorage


class LinkTocStage(BaseStage):
    """
    Link-ToC Stage: Map ToC entries to scan page numbers.

    Uses agent-per-entry approach where each ToC entry gets its own agent
    to search the book and find where it appears.

    Dependencies:
    - find-toc: Provides ToC page range to exclude from searches
    - extract-toc: Provides ToC entries to search for
    - label-pages: Provides boundary detection for efficient searching
    - ocr-pages: Provides OCR text for verification
    """

    name = "link-toc"
    dependencies = ["find-toc", "extract-toc", "label-pages", "ocr-pages"]

    output_schema = LinkedTableOfContents
    checkpoint_schema = None  # No checkpoints needed (single-phase)
    report_schema = None  # CSV handled separately
    self_validating = True

    def __init__(
        self,
        model: str = None,
        max_iterations: int = 15,
        verbose: bool = False
    ):
        super().__init__()

        from infra.config import Config
        self.model = model or Config.text_model_expensive
        self.max_iterations = max_iterations
        self.verbose = verbose

        self.status_tracker = LinkTocStatusTracker(stage_name=self.name)
        self.stage_storage = LinkTocStageStorage(stage_name=self.name)

    def get_status(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        """Get status from disk artifacts."""
        return self.status_tracker.get_status(storage)

    def pretty_print_status(self, status: Dict[str, Any]) -> str:
        """Return formatted link-toc status."""
        lines = []

        stage_status = status.get('status', 'unknown')
        lines.append(f"   Status: {stage_status}")

        total_entries = status.get('total_entries', 0)
        completed_entries = status.get('completed_entries', 0)
        found_entries = status.get('found_entries', 0)

        if total_entries > 0:
            if completed_entries < total_entries:
                lines.append(f"   Progress: {completed_entries}/{total_entries} entries ({found_entries} found)")
            else:
                lines.append(f"   Entries: {found_entries}/{total_entries} found")

        avg_confidence = status.get('avg_confidence', 0.0)
        if avg_confidence > 0:
            lines.append(f"   Avg Confidence: {avg_confidence:.2f}")

        metrics = status.get('metrics', {})
        if metrics.get('total_cost_usd', 0) > 0:
            lines.append(f"   Cost:    ${metrics['total_cost_usd']:.4f}")
        if metrics.get('stage_runtime_seconds', 0) > 0:
            mins = metrics['stage_runtime_seconds'] / 60
            lines.append(f"   Time:    {mins:.1f}m")

        return '\n'.join(lines)

    def before(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ):
        """Validate dependencies are complete."""
        logger.info(f"Link-ToC with {self.model}")
        logger.info(f"Max iterations per entry: {self.max_iterations}")

        # Check find-toc completed
        from pipeline.find_toc import FindTocStage
        find_toc_stage = FindTocStage()
        find_toc_progress = find_toc_stage.get_status(storage, logger)

        if find_toc_progress['status'] != 'completed':
            raise RuntimeError(
                f"find-toc stage status is '{find_toc_progress['status']}', not 'completed'. "
                f"Run find-toc stage to completion first."
            )

        # Check extract-toc completed
        from pipeline.extract_toc import ExtractTocStage
        extract_toc_stage = ExtractTocStage()
        extract_toc_progress = extract_toc_stage.get_status(storage, logger)

        if extract_toc_progress['status'] != 'completed':
            raise RuntimeError(
                f"extract-toc stage status is '{extract_toc_progress['status']}', not 'completed'. "
                f"Run extract-toc stage to completion first."
            )

        # Check label-pages completed
        from pipeline.label_pages import LabelPagesStage
        label_pages_stage = LabelPagesStage()
        label_pages_progress = label_pages_stage.get_status(storage, logger)

        if label_pages_progress['status'] != 'completed':
            raise RuntimeError(
                f"label-pages stage status is '{label_pages_progress['status']}', not 'completed'. "
                f"Run label-pages stage to completion first."
            )

        # Check ocr-pages completed
        from pipeline.ocr_pages import OcrPagesStage
        ocr_pages_stage = OcrPagesStage()
        ocr_pages_progress = ocr_pages_stage.get_status(storage, logger)

        if ocr_pages_progress['status'] != 'completed':
            raise RuntimeError(
                f"ocr-pages stage status is '{ocr_pages_progress['status']}', not 'completed'. "
                f"Run ocr-pages stage to completion first."
            )

        # Load and log ToC entry count
        extract_toc_output = self.stage_storage.load_extract_toc_output(storage)
        toc_data = extract_toc_output.get('toc', {}) if extract_toc_output else {}
        toc_entries = toc_data.get('entries', [])
        logger.info(f"ToC entries to process: {len(toc_entries)}")

        # Load and log boundary page count
        boundary_pages = self.stage_storage.load_boundary_pages(storage)
        logger.info(f"Boundary pages available: {len(boundary_pages)}")

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:
        """Execute link-toc stage with if-gates."""
        start_time = time.time()

        progress = self.get_status(storage, logger)
        status = progress["status"]

        logger.info(f"Status: {status}")

        if progress["status"] == LinkTocStatus.COMPLETED.value:
            logger.info("Link-toc already completed (skipping)")
            return {
                "status": "skipped",
                "reason": "already completed",
                "total_entries": progress["total_entries"],
                "found_entries": progress["found_entries"]
            }

        # If-gate 1: Find all ToC entries
        if not progress["artifacts"]["linked_toc_exists"]:
            logger.info("=== Finding ToC Entries ===")

            from .orchestrator import find_all_toc_entries

            output, metrics = find_all_toc_entries(
                storage=storage,
                logger=logger,
                model=self.model,
                max_iterations=self.max_iterations,
                verbose=self.verbose
            )

            self.stage_storage.save_linked_toc(storage, output)

            # Record metrics
            stage_storage_obj = storage.stage(self.name)
            stage_storage_obj.metrics_manager.record(
                key="find_entries",
                cost_usd=metrics['cost_usd'],
                time_seconds=metrics['time_seconds'],
                custom_metrics={
                    "total_entries": metrics['total_entries'],
                    "found_entries": metrics['found_count'],
                }
            )

            progress = self.get_status(storage, logger)

        # If-gate 2: Generate report
        if not progress["artifacts"]["report_exists"]:
            logger.info("=== Generating Report ===")

            from .tools.report_generator import generate_report

            generate_report(
                storage=storage,
                logger=logger,
                stage_storage=self.stage_storage
            )

            progress = self.get_status(storage, logger)

        # Record total stage runtime (accumulate across runs for resume support)
        elapsed_time = time.time() - start_time
        stage_storage_obj = storage.stage(self.name)
        stage_storage_obj.metrics_manager.record(
            key="stage_runtime",
            time_seconds=elapsed_time,
            accumulate=True
        )

        # Load final statistics
        linked_toc = self.stage_storage.load_linked_toc(storage)
        total_cost = progress["metrics"]["total_cost_usd"]

        logger.info(
            "Link-toc complete",
            total_entries=linked_toc.total_entries,
            found=linked_toc.linked_entries,
            not_found=linked_toc.unlinked_entries,
            avg_confidence=f"{linked_toc.avg_link_confidence:.2f}",
            cost=f"${total_cost:.4f}",
            time=f"{elapsed_time:.1f}s"
        )

        return {
            "status": "success",
            "total_entries": linked_toc.total_entries,
            "found_entries": linked_toc.linked_entries,
            "not_found_entries": linked_toc.unlinked_entries,
            "avg_confidence": linked_toc.avg_link_confidence,
            "cost_usd": total_cost,
            "time_seconds": elapsed_time
        }
