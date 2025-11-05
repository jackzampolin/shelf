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
            artifacts.get('finder_result_exists', False),
            artifacts.get('ocr_text_exists', False),
            artifacts.get('elements_identified_exists', False),
            artifacts.get('toc_validated_exists', False),
        ])
        total_phases = 4
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
            print("\n🤖 Phase 1: Agent search for ToC")

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

        # Phase 2: OCR text extraction with OlmOCR
        if not progress["artifacts"]["ocr_text_exists"]:
            logger.info("=== Phase 2: OCR Text Extraction ===")
            print("🔍 Phase 2: OCR ToC pages")

            finder_result = self.stage_storage.load_finder_result(storage)
            from .schemas import PageRange
            toc_range = PageRange(**finder_result["toc_page_range"])

            from .phase_2 import extract_ocr_text

            ocr_data, phase2_metrics = extract_ocr_text(
                storage=storage,
                toc_range=toc_range,
                logger=logger
            )

            self.stage_storage.save_ocr_text(storage, ocr_data)

            stage_storage_obj = storage.stage(self.name)
            stage_storage_obj.metrics_manager.record(
                key="phase2_ocr_extraction",
                cost_usd=phase2_metrics['cost_usd'],
                time_seconds=phase2_metrics['time_seconds'],
                custom_metrics={
                    "phase": "ocr_text",
                    "pages_processed": phase2_metrics['pages_processed'],
                    "total_chars": phase2_metrics['total_chars'],
                    "prompt_tokens": phase2_metrics['prompt_tokens'],
                    "completion_tokens": phase2_metrics['completion_tokens'],
                }
            )

            logger.info(f"Saved ocr_text.json + {phase2_metrics['pages_processed']} markdown files")
            progress = self.get_status(storage, logger)

        # Phase 3: Identify structural elements (vision + OCR text)
        if not progress["artifacts"]["elements_identified_exists"]:
            logger.info("=== Phase 3: Identify Structural Elements ===")
            print("👁️  Phase 3: Element identification")

            finder_result = self.stage_storage.load_finder_result(storage)
            from .schemas import PageRange
            toc_range = PageRange(**finder_result["toc_page_range"])
            structure_notes_from_finder = finder_result.get("structure_notes") or {}

            from .phase_3 import identify_elements

            elements_data, phase3_metrics = identify_elements(
                storage=storage,
                toc_range=toc_range,
                structure_notes_from_finder=structure_notes_from_finder,
                logger=logger,
                model=self.model
            )

            self.stage_storage.save_elements_identified(storage, elements_data)

            stage_storage_obj = storage.stage(self.name)
            stage_storage_obj.metrics_manager.record(
                key="phase3_element_identification",
                cost_usd=phase3_metrics['cost_usd'],
                time_seconds=phase3_metrics['time_seconds'],
                custom_metrics={
                    "phase": "identify_elements",
                    "pages_processed": phase3_metrics['pages_processed'],
                    "total_elements": phase3_metrics['total_elements'],
                    "completion_tokens": phase3_metrics['completion_tokens'],
                    "prompt_tokens": phase3_metrics['prompt_tokens'],
                    "reasoning_tokens": phase3_metrics['reasoning_tokens'],
                }
            )

            logger.info(f"Saved elements_identified.json ({phase3_metrics['total_elements']} elements from {phase3_metrics['pages_processed']} pages)")
            progress = self.get_status(storage, logger)

        # Phase 4: Validate and assemble ToC
        if not progress["artifacts"]["toc_validated_exists"]:
            logger.info("=== Phase 4: Validate and Assemble ToC ===")
            print("📝 Phase 4: Validate and assemble ToC")

            finder_result = self.stage_storage.load_finder_result(storage)
            from .schemas import PageRange
            toc_range = PageRange(**finder_result["toc_page_range"])

            from .phase_4 import validate_and_assemble

            toc_data, phase4_metrics = validate_and_assemble(
                storage=storage,
                toc_range=toc_range,
                logger=logger,
                model=self.model
            )

            self.stage_storage.save_toc_validated(storage, toc_data)

            stage_storage_obj = storage.stage(self.name)
            stage_storage_obj.metrics_manager.record(
                key="phase4_validation",
                cost_usd=phase4_metrics['cost_usd'],
                time_seconds=phase4_metrics['time_seconds'],
                custom_metrics={
                    "phase": "validation",
                    "total_entries": phase4_metrics['total_entries'],
                    "confidence": phase4_metrics['confidence'],
                    "issues_found": phase4_metrics['issues_found'],
                    "completion_tokens": phase4_metrics['completion_tokens'],
                    "prompt_tokens": phase4_metrics['prompt_tokens'],
                    "reasoning_tokens": phase4_metrics['reasoning_tokens'],
                }
            )

            logger.info(f"Saved toc.json ({phase4_metrics['total_entries']} entries, confidence={phase4_metrics['confidence']:.2f})")
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
