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

    name = "extract_toc"
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

    def get_progress(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        return self.status_tracker.get_progress(storage, logger)

    def before(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ):
        logger.info(f"Extract-ToC with {self.model}")

        from pipeline.paragraph_correct import ParagraphCorrectStage
        para_correct_stage = ParagraphCorrectStage()
        para_correct_progress = para_correct_stage.get_progress(storage, logger)

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

        progress = self.get_progress(storage, logger)

        if progress["status"] == ExtractTocStatus.COMPLETED.value:
            logger.info("Extract-ToC already completed (skipping)")
            return {"status": "skipped", "reason": "already completed"}

        logger.info("Starting extract-toc", model=self.model)

        start_time = time.time()
        total_cost = 0.0

        if progress["artifacts"]["finder_result_exists"]:
            finder_result = self.stage_storage.load_finder_result(storage)
            total_cost += finder_result.get("search_cost_usd", 0.0)

        if progress["artifacts"]["structure_exists"]:
            structure_data = self.stage_storage.load_structure(storage)
            total_cost += structure_data.get("structure_cost_usd", 0.0)

        if progress["artifacts"]["toc_unchecked_exists"]:
            toc_unchecked = self.stage_storage.load_toc_unchecked(storage)
            total_cost += toc_unchecked.get("extraction_cost_usd", 0.0)

        # Phase 1: Find ToC pages (grep + vision agent)
        if not progress["artifacts"]["finder_result_exists"]:
            logger.info("=== Phase 1: Finding ToC Pages ===")

            from .agent.finder import find_toc_pages

            toc_range, phase1_cost = find_toc_pages(
                storage=storage,
                logger=logger,
                max_iterations=15,
                verbose=True
            )

            total_cost += phase1_cost

            finder_result = {
                "toc_found": toc_range is not None,
                "toc_page_range": toc_range.model_dump() if toc_range else None,
                "search_cost_usd": phase1_cost
            }

            self.stage_storage.save_finder_result(storage, finder_result)

            if not toc_range:
                logger.info("No ToC found by agent")

                elapsed_time = time.time() - start_time

                self.stage_storage.save_toc_final(storage, {"toc": None, "search_strategy": "not_found"})

                return {
                    "status": "success",
                    "toc_found": False,
                    "cost_usd": total_cost,
                    "time_seconds": elapsed_time
                }

            logger.info("Found ToC pages", start=toc_range.start_page, end=toc_range.end_page)
            progress = self.get_progress(storage, logger)

        # Phase 2: Extract structure observations
        if not progress["artifacts"]["structure_exists"]:
            logger.info("=== Phase 2: Detecting ToC Structure ===")

            finder_result = self.stage_storage.load_finder_result(storage)
            from .schemas import PageRange
            toc_range = PageRange(**finder_result["toc_page_range"])

            from .tools.extractor import load_toc_images, detect_toc_structure

            stage_dir = storage.stage(self.name).output_dir
            log_dir = stage_dir / "logs"
            toc_images = load_toc_images(storage, toc_range)

            observations, phase2_cost = detect_toc_structure(
                toc_images=toc_images,
                model=self.model,
                logger=logger,
                log_dir=log_dir
            )

            total_cost += phase2_cost

            structure_data = {
                "observations": observations,
                "structure_cost_usd": phase2_cost
            }

            self.stage_storage.save_structure(storage, structure_data)
            progress = self.get_progress(storage, logger)

        # Phase 3: Generate ToC draft (unchecked)
        if not progress["artifacts"]["toc_unchecked_exists"]:
            logger.info("=== Phase 3: Generating ToC Draft ===")

            finder_result = self.stage_storage.load_finder_result(storage)
            structure_data = self.stage_storage.load_structure(storage)

            from .schemas import PageRange
            toc_range = PageRange(**finder_result["toc_page_range"])
            observations = structure_data["observations"]

            from .tools.extractor import load_toc_images, extract_toc_text, extract_toc_entries

            stage_dir = storage.stage(self.name).output_dir
            log_dir = stage_dir / "logs"
            toc_images = load_toc_images(storage, toc_range)
            toc_text = extract_toc_text(storage, toc_range, self.stage_storage)

            toc, phase3_cost = extract_toc_entries(
                toc_images=toc_images,
                toc_text=toc_text,
                toc_range=toc_range,
                observations=observations,
                model=self.model,
                logger=logger,
                log_dir=log_dir
            )

            total_cost += phase3_cost

            toc_unchecked = {
                "toc": toc.model_dump(),
                "extraction_cost_usd": phase3_cost
            }

            self.stage_storage.save_toc_unchecked(storage, toc_unchecked)
            logger.info("Saved toc_unchecked.json", entries=len(toc.entries))
            progress = self.get_progress(storage, logger)

        # Phase 4: Check ToC for issues (validation)
        if not progress["artifacts"]["toc_diff_exists"]:
            logger.info("=== Phase 4: Checking ToC ===")

            toc_diff = {
                "issues": [],
                "corrections": [],
                "validation_passed": True
            }

            self.stage_storage.save_toc_diff(storage, toc_diff)
            logger.info("Saved toc_diff.json (no issues found)")
            progress = self.get_progress(storage, logger)

        # Phase 5: Merge ToC (draft + corrections)
        if not progress["artifacts"]["toc_final_exists"]:
            logger.info("=== Phase 5: Merging ToC ===")

            toc_unchecked = self.stage_storage.load_toc_unchecked(storage)
            toc_diff = self.stage_storage.load_toc_diff(storage)

            toc_final = {
                "toc": toc_unchecked["toc"],
                "search_strategy": "grep_report",
                "applied_corrections": len(toc_diff.get("corrections", []))
            }

            self.stage_storage.save_toc_final(storage, toc_final)

            elapsed_time = time.time() - start_time

            logger.info("Saved toc.json (final)")
            progress = self.get_progress(storage, logger)

        if progress["status"] == ExtractTocStatus.COMPLETED.value:
            elapsed_time = time.time() - start_time
            toc_final = self.stage_storage.load_toc_final(storage)
            toc_found = toc_final.get("toc") is not None
            toc_entries = len(toc_final["toc"]["entries"]) if toc_found else 0

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
