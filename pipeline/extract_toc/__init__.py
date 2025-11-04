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
    dependencies = ["paragraph-correct", "source"]

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

        # Extract-toc specific: Phase-based status (not page-based)
        stage_status = status.get('status', 'unknown')
        lines.append(f"   Status: {stage_status}")

        # Cost and time metrics
        metrics = status.get('metrics', {})
        if metrics.get('total_cost_usd', 0) > 0:
            lines.append(f"   Cost:   ${metrics['total_cost_usd']:.4f}")
        if metrics.get('total_time_seconds', 0) > 0:
            mins = metrics['total_time_seconds'] / 60
            lines.append(f"   Time:   {mins:.1f}m")

        # Extract-toc specific: Phase completion
        artifacts = status.get('artifacts', {})
        phases_completed = sum([
            artifacts.get('finder_result_exists', False),
            artifacts.get('bboxes_extracted_exists', False),
            artifacts.get('bboxes_verified_exists', False),
            artifacts.get('bboxes_ocr_exists', False),
            artifacts.get('toc_assembled_exists', False),
            artifacts.get('toc_validated_exists', False),
        ])
        total_phases = 6
        lines.append(f"   Phases: {phases_completed}/{total_phases} completed")

        return '\n'.join(lines)

    def before(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ):
        logger.info(f"Extract-ToC with {self.model}")

        from pipeline.paragraph_correct import ParagraphCorrectStage
        para_correct_stage = ParagraphCorrectStage()
        para_correct_progress = para_correct_stage.get_status(storage, logger)

        if para_correct_progress['status'] != 'completed':
            raise RuntimeError(
                f"Paragraph-correct stage status is '{para_correct_progress['status']}', not 'completed'. "
                f"Run paragraph-correct stage to completion first."
            )

        logger.info(f"Paragraph-correct completed: {para_correct_progress['total_pages']} pages ready")

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

        # Phase 1: Find ToC pages (grep + vision agent)
        if not progress["artifacts"]["finder_result_exists"]:
            logger.info("=== Phase 1: Finding ToC Pages ===")

            from .agent.finder import TocFinderAgent

            agent = TocFinderAgent(
                storage=storage,
                logger=logger,
                max_iterations=15,
                verbose=True
            )

            result = agent.search()

            finder_result = {
                "toc_found": result.toc_found,
                "toc_page_range": result.toc_page_range.model_dump() if result.toc_page_range else None,
                "structure_notes": result.structure_notes,
            }

            self.stage_storage.save_finder_result(storage, finder_result)
            toc_range = result.toc_page_range

            if not toc_range:
                logger.info("No ToC found by agent")

                elapsed_time = time.time() - start_time

                self.stage_storage.save_toc_final(storage, {"toc": None, "search_strategy": "not_found"})

                stage_storage_obj = storage.stage(self.name)
                total_cost = sum(m.get('cost_usd', 0.0) for m in stage_storage_obj.metrics_manager.get_all().values())

                # Record stage runtime
                stage_storage_obj.metrics_manager.record(
                    key="stage_runtime",
                    time_seconds=elapsed_time
                )

                return {
                    "status": "success",
                    "toc_found": False,
                    "cost_usd": total_cost,
                    "time_seconds": elapsed_time
                }

            logger.info("Found ToC pages", start=toc_range.start_page, end=toc_range.end_page)
            progress = self.get_status(storage, logger)

        # Phase 2: Extract bboxes (vision model places boxes)
        if not progress["artifacts"]["bboxes_extracted_exists"]:
            logger.info("=== Phase 2: Extracting Bounding Boxes ===")

            finder_result = self.stage_storage.load_finder_result(storage)
            from .schemas import PageRange
            toc_range = PageRange(**finder_result["toc_page_range"])
            structure_notes_from_finder = finder_result.get("structure_notes")

            from .phase_2 import extract_bboxes

            bboxes_data, phase2_metrics = extract_bboxes(
                storage=storage,
                toc_range=toc_range,
                structure_notes_from_finder=structure_notes_from_finder,
                logger=logger,
                model=self.model
            )

            self.stage_storage.save_bboxes_extracted(storage, bboxes_data)

            stage_storage_obj = storage.stage(self.name)
            stage_storage_obj.metrics_manager.record(
                key="phase2_bbox_extraction",
                cost_usd=phase2_metrics['cost_usd'],
                time_seconds=phase2_metrics['time_seconds'],
                custom_metrics={
                    "phase": "bbox_extraction",
                    "pages_processed": phase2_metrics['pages_processed'],
                    "completion_tokens": phase2_metrics['completion_tokens'],
                    "prompt_tokens": phase2_metrics['prompt_tokens'],
                    "reasoning_tokens": phase2_metrics['reasoning_tokens'],
                }
            )

            logger.info(f"Saved bboxes_extracted.json ({phase2_metrics['pages_processed']} pages)")
            progress = self.get_status(storage, logger)

        # Phase 3: Verify bboxes (self-check)
        if not progress["artifacts"]["bboxes_verified_exists"]:
            logger.info("=== Phase 3: Verifying Bounding Boxes ===")

            finder_result = self.stage_storage.load_finder_result(storage)
            from .schemas import PageRange
            toc_range = PageRange(**finder_result["toc_page_range"])

            from .phase_3 import verify_bboxes

            verified_data, phase3_metrics = verify_bboxes(
                storage=storage,
                toc_range=toc_range,
                logger=logger,
                model=self.model
            )

            self.stage_storage.save_bboxes_verified(storage, verified_data)

            stage_storage_obj = storage.stage(self.name)
            stage_storage_obj.metrics_manager.record(
                key="phase3_bbox_verification",
                cost_usd=phase3_metrics['cost_usd'],
                time_seconds=phase3_metrics['time_seconds'],
                custom_metrics={
                    "phase": "bbox_verification",
                    "pages_processed": phase3_metrics['pages_processed'],
                    "total_corrections": phase3_metrics['total_corrections'],
                    "completion_tokens": phase3_metrics['completion_tokens'],
                    "prompt_tokens": phase3_metrics['prompt_tokens'],
                    "reasoning_tokens": phase3_metrics['reasoning_tokens'],
                }
            )

            logger.info(f"Saved bboxes_verified.json ({phase3_metrics['total_corrections']} corrections applied)")
            progress = self.get_status(storage, logger)

        # Phase 4: OCR bboxes (Tesseract extracts text)
        if not progress["artifacts"]["bboxes_ocr_exists"]:
            logger.info("=== Phase 4: OCR Bounding Boxes ===")

            finder_result = self.stage_storage.load_finder_result(storage)
            from .schemas import PageRange
            toc_range = PageRange(**finder_result["toc_page_range"])

            from .phase_4 import ocr_bboxes

            ocr_data, phase4_metrics = ocr_bboxes(
                storage=storage,
                toc_range=toc_range,
                logger=logger
            )

            self.stage_storage.save_bboxes_ocr(storage, ocr_data)

            stage_storage_obj = storage.stage(self.name)
            stage_storage_obj.metrics_manager.record(
                key="phase4_bbox_ocr",
                time_seconds=phase4_metrics['time_seconds'],
                custom_metrics={
                    "phase": "bbox_ocr",
                    "pages_processed": phase4_metrics['pages_processed'],
                    "total_bboxes": phase4_metrics['total_bboxes'],
                    "avg_confidence": phase4_metrics['avg_confidence'],
                }
            )

            logger.info(f"Saved bboxes_ocr.json ({phase4_metrics['total_bboxes']} boxes, {phase4_metrics['avg_confidence']:.1f}% avg conf)")
            progress = self.get_status(storage, logger)

        # Phase 5: Assemble ToC (page-by-page with prior context)
        if not progress["artifacts"]["toc_assembled_exists"]:
            logger.info("=== Phase 5: Assembling ToC ===")

            finder_result = self.stage_storage.load_finder_result(storage)
            from .schemas import PageRange
            toc_range = PageRange(**finder_result["toc_page_range"])

            from .phase_5 import assemble_toc

            assembly_data, phase5_metrics = assemble_toc(
                storage=storage,
                toc_range=toc_range,
                logger=logger,
                model=self.model
            )

            self.stage_storage.save_toc_assembled(storage, assembly_data)

            stage_storage_obj = storage.stage(self.name)
            stage_storage_obj.metrics_manager.record(
                key="phase5_toc_assembly",
                cost_usd=phase5_metrics['cost_usd'],
                time_seconds=phase5_metrics['time_seconds'],
                custom_metrics={
                    "phase": "toc_assembly",
                    "pages_processed": phase5_metrics['pages_processed'],
                    "total_entries": phase5_metrics['total_entries'],
                    "completion_tokens": phase5_metrics['completion_tokens'],
                    "prompt_tokens": phase5_metrics['prompt_tokens'],
                    "reasoning_tokens": phase5_metrics['reasoning_tokens'],
                }
            )

            logger.info(f"Saved toc_assembled.json ({phase5_metrics['total_entries']} entries from {phase5_metrics['pages_processed']} pages)")
            progress = self.get_status(storage, logger)

        # Phase 6: Validate ToC (final consistency check)
        if not progress["artifacts"]["toc_validated_exists"]:
            logger.info("=== Phase 6: Validating ToC ===")

            finder_result = self.stage_storage.load_finder_result(storage)
            from .schemas import PageRange
            toc_range = PageRange(**finder_result["toc_page_range"])

            from .phase_6 import validate_toc

            validation_data, phase6_metrics = validate_toc(
                storage=storage,
                toc_range=toc_range,
                logger=logger
            )

            self.stage_storage.save_toc_validated(storage, validation_data)

            stage_storage_obj = storage.stage(self.name)
            stage_storage_obj.metrics_manager.record(
                key="phase6_toc_validation",
                time_seconds=phase6_metrics['time_seconds'],
                custom_metrics={
                    "phase": "toc_validation",
                    "total_entries": phase6_metrics['total_entries'],
                    "total_chapters": phase6_metrics['total_chapters'],
                    "total_sections": phase6_metrics['total_sections'],
                    "validation_issues": phase6_metrics['validation_issues'],
                }
            )

            logger.info(f"Saved toc_validated.json ({phase6_metrics['total_entries']} entries, {phase6_metrics['validation_issues']} issues)")
            progress = self.get_status(storage, logger)

        if progress["status"] == ExtractTocStatus.COMPLETED.value:
            elapsed_time = time.time() - start_time
            toc_final = self.stage_storage.load_toc_validated(storage)
            toc_found = toc_final.get("toc") is not None
            toc_entries = len(toc_final["toc"]["entries"]) if toc_found else 0

            stage_storage_obj = storage.stage(self.name)
            total_cost = sum(m.get('cost_usd', 0.0) for m in stage_storage_obj.metrics_manager.get_all().values())

            # Record stage runtime (only if not already recorded)
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
