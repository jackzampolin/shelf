import time
from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.config import Config

from .schemas import ExtractTocBookOutput
from .status import ExtractTocStatusTracker, ExtractTocStatus
from .storage import ExtractTocStageStorage


class ExtractTocStage(BaseStage):

    name = "extract-toc"
    dependencies = ["source", "find-toc", "ocr-pages"]

    output_schema = ExtractTocBookOutput
    checkpoint_schema = None
    report_schema = None
    self_validating = True

    def __init__(self, model: str = None):
        super().__init__()
        self.model = model or Config.text_model_expensive
        self.status_tracker = ExtractTocStatusTracker(stage_name=self.name)
        self.stage_storage = ExtractTocStageStorage(stage_name=self.name)

    def get_status(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        return self.status_tracker.get_status(storage)

    def pretty_print_status(self, status: Dict[str, Any]) -> str:
        lines = []

        stage_status = status.get('status', 'unknown')
        lines.append(f"   Status: {stage_status}")

        metrics = status.get('metrics', {})
        if metrics.get('total_cost_usd', 0) > 0:
            lines.append(f"   Cost:   ${metrics['total_cost_usd']:.4f}")
        if metrics.get('total_time_seconds', 0) > 0:
            mins = metrics['total_time_seconds'] / 60
            lines.append(f"   Time:   {mins:.1f}m")

        artifacts = status.get('artifacts', {})
        phases_completed = sum([
            artifacts.get('entries_extracted_exists', False),
            artifacts.get('toc_validated_exists', False),
        ])
        total_phases = 2
        lines.append(f"   Phases: {phases_completed}/{total_phases} completed")

        return '\n'.join(lines)

    def before(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ):
        logger.info(f"Extract-ToC with {self.model}")

        # Check source dependency
        source_storage = storage.stage("source")
        source_pages = source_storage.list_output_pages(extension="png")
        if len(source_pages) == 0:
            raise RuntimeError("Source stage has no pages. Run source stage first.")
        logger.info(f"Source stage: {len(source_pages)} pages available")

        # Check find-toc dependency
        from pipeline.find_toc import FindTocStage
        find_toc_stage = FindTocStage()
        find_toc_progress = find_toc_stage.get_status(storage, logger)

        if find_toc_progress['status'] != 'completed':
            raise RuntimeError(
                f"Find-toc stage status is '{find_toc_progress['status']}', not 'completed'. "
                f"Run find-toc stage to completion first."
            )

        # Load finder result to check if ToC was found
        from pipeline.find_toc.storage import FindTocStageStorage
        find_toc_storage = FindTocStageStorage(stage_name='find-toc')
        finder_result = find_toc_storage.load_finder_result(storage)

        if not finder_result or not finder_result.get('toc_found'):
            raise RuntimeError(
                f"Find-toc stage completed but no ToC was found. "
                f"Cannot proceed with ToC extraction."
            )

        toc_range = finder_result.get('toc_page_range')
        logger.info(f"Find-toc found ToC: pages {toc_range['start_page']}-{toc_range['end_page']}")

        # Check ocr-pages dependency
        from pipeline.ocr_pages import OcrPagesStage
        ocr_pages_stage = OcrPagesStage()
        ocr_pages_progress = ocr_pages_stage.get_status(storage, logger)

        if ocr_pages_progress['status'] != 'completed':
            raise RuntimeError(
                f"OCR-pages stage status is '{ocr_pages_progress['status']}', not 'completed'. "
                f"Run ocr-pages stage to completion first."
            )

        logger.info(f"OCR-pages completed: {ocr_pages_progress['completed_pages']} pages ready")

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
    ) -> Dict[str, Any]:

        progress = self.get_status(storage, logger)

        if progress["status"] == ExtractTocStatus.COMPLETED.value:
            logger.info("Extract-ToC already completed (skipping)")
            return {"status": "skipped", "reason": "already completed"}

        logger.info("Starting extract-toc", model=self.model)

        start_time = time.time()

        # Load finder result from find-toc stage
        from pipeline.find_toc.storage import FindTocStageStorage
        find_toc_storage = FindTocStageStorage(stage_name='find-toc')
        finder_result = find_toc_storage.load_finder_result(storage)
        from .schemas import PageRange
        toc_range = PageRange(**finder_result["toc_page_range"])
        structure_notes_from_finder = finder_result.get("structure_notes") or {}

        logger.info("Using ToC range from find-toc", start=toc_range.start_page, end=toc_range.end_page)

        # Phase 1: Extract ToC entries directly (vision + OCR from ocr-pages)
        if not progress["artifacts"]["entries_extracted_exists"]:
            logger.info("=== Phase 1: Extract ToC Entries ===")
            print("👁️  Phase 1: Extract ToC entries")

            from .phase_2 import extract_toc_entries

            entries_data, phase1_metrics = extract_toc_entries(
                storage=storage,
                toc_range=toc_range,
                structure_notes_from_finder=structure_notes_from_finder,
                logger=logger,
                model=self.model
            )

            self.stage_storage.save_entries_extracted(storage, entries_data)

            stage_storage_obj = storage.stage(self.name)
            stage_storage_obj.metrics_manager.record(
                key="phase1_entry_extraction",
                cost_usd=phase1_metrics['cost_usd'],
                time_seconds=phase1_metrics['time_seconds'],
                custom_metrics={
                    "phase": "extract_entries",
                    "pages_processed": phase1_metrics['pages_processed'],
                    "total_entries": phase1_metrics['total_entries'],
                    "completion_tokens": phase1_metrics['completion_tokens'],
                    "prompt_tokens": phase1_metrics['prompt_tokens'],
                    "reasoning_tokens": phase1_metrics['reasoning_tokens'],
                }
            )

            logger.info(f"Saved entries.json ({phase1_metrics['total_entries']} entries from {phase1_metrics['pages_processed']} pages)")
            progress = self.get_status(storage, logger)

        # Phase 2: Assemble ToC (lightweight merge & validation)
        if not progress["artifacts"]["toc_validated_exists"]:
            logger.info("=== Phase 2: Assemble ToC ===")
            print("📝 Phase 2: Assemble and validate ToC")

            from .phase_3 import assemble_toc

            toc_data, phase2_metrics = assemble_toc(
                storage=storage,
                toc_range=toc_range,
                logger=logger,
                model=self.model
            )

            self.stage_storage.save_toc_validated(storage, toc_data)

            stage_storage_obj = storage.stage(self.name)
            stage_storage_obj.metrics_manager.record(
                key="phase2_assembly",
                cost_usd=phase2_metrics['cost_usd'],
                time_seconds=phase2_metrics['time_seconds'],
                custom_metrics={
                    "phase": "assembly",
                    "total_entries": phase2_metrics['total_entries'],
                    "confidence": phase2_metrics['confidence'],
                    "issues_found": phase2_metrics['issues_found'],
                    "completion_tokens": phase2_metrics['completion_tokens'],
                    "prompt_tokens": phase2_metrics['prompt_tokens'],
                    "reasoning_tokens": phase2_metrics['reasoning_tokens'],
                }
            )

            logger.info(f"Saved toc.json ({phase2_metrics['total_entries']} entries, confidence={phase2_metrics['confidence']:.2f})")
            progress = self.get_status(storage, logger)

        if progress["status"] == ExtractTocStatus.COMPLETED.value:
            elapsed_time = time.time() - start_time
            toc_final = self.stage_storage.load_toc_validated(storage)
            toc_found = toc_final.get("toc") is not None
            toc_entries = len(toc_final["toc"]["entries"]) if toc_found else 0

            stage_storage_obj = storage.stage(self.name)
            total_cost = sum(m.get('cost_usd', 0.0) for m in stage_storage_obj.metrics_manager.get_all().values())

            # Calculate total tokens across all phases
            all_metrics = stage_storage_obj.metrics_manager.get_all()
            total_prompt_tokens = 0
            total_completion_tokens = 0
            total_reasoning_tokens = 0

            for metric in all_metrics.values():
                custom = metric.get('custom_metrics', {})
                total_prompt_tokens += custom.get('prompt_tokens', 0)
                total_completion_tokens += custom.get('completion_tokens', 0)
                total_reasoning_tokens += custom.get('reasoning_tokens', 0)

            # Print final summary line
            from infra.llm.display_format import format_batch_summary
            from rich.console import Console

            summary = format_batch_summary(
                batch_name="Extract-ToC complete",
                completed=toc_entries,
                total=toc_entries,
                time_seconds=elapsed_time,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                reasoning_tokens=total_reasoning_tokens,
                cost_usd=total_cost,
                unit="entries"
            )
            print()  # Blank line before final summary
            Console().print(summary)

            runtime_metrics = stage_storage_obj.metrics_manager.get("stage_runtime")
            if not runtime_metrics:
                stage_storage_obj.metrics_manager.record(
                    key="stage_runtime",
                    time_seconds=elapsed_time
                )

            logger.info(
                "Extract-ToC complete",
                toc_found=toc_found,
                entries=toc_entries,
                cost=f"${total_cost:.4f}",
                time=f"{elapsed_time:.1f}s"
            )

            return {
                "status": "success",
                "toc_found": toc_found,
                "toc_entries": toc_entries,
                "cost_usd": total_cost,
                "time_seconds": elapsed_time
            }

        return {
            "status": "incomplete",
            "phase_completed": 4,
            "cost_usd": 0.0,
            "time_seconds": 0.0
        }
