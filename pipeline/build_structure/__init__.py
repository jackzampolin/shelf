"""
Build-structure stage: Extract and validate book structure metadata.

This stage operates on the entire book (not per-page) to identify:
- Front matter (title, copyright, TOC, preface, etc.)
- Chapters and sections
- Back matter (epilogue, notes, bibliography, index, etc.)
- Page numbering patterns

Three-phase processing:
1. Phase 1a: Parse ToC (if detected)
2. Phase 1.5: Extract heading text from chapter heading pages
3. Phase 1b: LLM analyzes labels/report.csv -> DraftMetadata (~$0.10-0.20, 10-30s)
4. Phase 2: Validate against merged/ pages -> ValidationResult (~$0-1, 1-2min)
5. Phase 3: Output validated structure.json

Dependencies: merged, labels
Output: build_structure/structure.json
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.config import Config

from .schemas import BookStructureMetadata
from .toc import parse_toc
from .headings import extract_headings
from .analyze import analyze_report
from .validate import validate_structure


class BuildStructureStage(BaseStage):
    """
    Build-structure stage: Extract and validate book structure.

    This stage is book-level (not per-page), so we use page_num=1 as a
    sentinel value to fit the BaseStage contract.
    """

    name = "build_structure"
    dependencies = ["merged", "labels"]

    # No output schema (writes to structure.json, not per-page outputs)
    output_schema = None
    checkpoint_schema = None
    report_schema = None

    def __init__(self, model: str = None):
        """
        Initialize build-structure stage.

        Args:
            model: LLM model to use (defaults to Config.text_model_expensive)
                  Supports both internal thinking (claude-3.5-sonnet) and
                  extended thinking (claude-sonnet-4.5) models
        """
        super().__init__()
        self.model = model or Config.text_model_expensive

    def run(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger,
    ) -> dict:
        """
        Run build-structure stage.

        This is a book-level operation (not per-page), so we process once
        and mark page_num=1 as the sentinel "completed page".

        Args:
            storage: BookStorage instance
            checkpoint: CheckpointManager instance
            logger: PipelineLogger instance

        Returns:
            Statistics dict
        """
        # Check if already completed (resume support)
        remaining = checkpoint.get_remaining_pages(total_pages=1, resume=True)
        if not remaining:
            logger.info("Build-structure already completed (skipping)")
            return {"status": "skipped", "reason": "already completed"}

        logger.info("Starting build-structure", model=self.model)

        total_cost = 0.0
        stage_storage = storage.stage(self.name)

        # Phase 1a: Parse Table of Contents (provides top-down structure)
        labels_report_path = storage.book_dir / "labels" / "report.csv"
        toc, phase1a_cost = parse_toc(
            storage=storage,
            labels_report_path=labels_report_path,
            model=self.model,
            logger=logger,
        )

        total_cost += phase1a_cost

        # Save ToC to build_structure/toc.json (even if None)
        toc_path = stage_storage.output_dir / "toc.json"
        with open(toc_path, "w") as f:
            if toc:
                json.dump(toc.model_dump(), f, indent=2)
            else:
                json.dump({"note": "No ToC found in labels report"}, f, indent=2)

        if toc:
            logger.info("Saved toc.json", path=str(toc_path), entries=len(toc.entries))
        else:
            logger.info("No ToC found, saved placeholder toc.json", path=str(toc_path))

        # Phase 1.5: Extract heading text from all chapter heading pages
        heading_data = extract_headings(
            storage=storage,
            labels_report_path=labels_report_path,
            logger=logger,
        )

        # Save heading data to build_structure/headings.json
        headings_path = stage_storage.output_dir / "headings.json"
        with open(headings_path, "w") as f:
            json.dump(heading_data.model_dump(), f, indent=2)

        logger.info(
            "Saved headings.json",
            path=str(headings_path),
            total=heading_data.total_headings,
            parts=heading_data.part_count,
            chapters=heading_data.chapter_count,
        )

        # Phase 1b: Analyze report.csv (informed by ToC and heading data)
        draft, phase1b_cost = analyze_report(
            labels_report_path=labels_report_path,
            toc=toc,  # Pass ToC data to structure analysis
            heading_data=heading_data,  # Pass extracted heading text
            model=self.model,
            logger=logger,
        )

        total_cost += phase1b_cost

        # Phase 2: Restructure (if needed) and validate against merged pages with LLM verification
        draft, validation, phase2_cost = validate_structure(
            draft=draft,
            heading_data=heading_data,
            storage=storage,
            logger=logger,
            model=self.model,
            use_llm_verification=True,
        )

        total_cost += phase2_cost

        # Phase 3: Build final structure and save to build_structure/structure.json
        timestamp = datetime.now(timezone.utc).isoformat()

        structure_metadata = BookStructureMetadata(
            front_matter=draft.front_matter,
            parts=draft.parts,
            chapters=draft.chapters,
            back_matter=draft.back_matter,
            validation=validation,
            structure_extracted_at=timestamp,
            structure_cost_usd=total_cost,
            total_pages=len(storage.stage("merged").list_output_pages()),
            total_parts=draft.total_parts,
            total_chapters=draft.total_chapters,
            total_sections=draft.total_sections,
            body_page_range=draft.body_page_range,
        )

        # Save structure to build_structure/structure.json
        structure_path = stage_storage.output_dir / "structure.json"

        with open(structure_path, "w") as f:
            json.dump(structure_metadata.model_dump(), f, indent=2)

        logger.info("Saved structure.json", path=str(structure_path))

        # Mark complete (use page_num=1 as sentinel)
        checkpoint.mark_completed(
            page_num=1,
            cost_usd=total_cost,
            metrics={
                "total_parts": draft.total_parts,
                "total_chapters": draft.total_chapters,
                "total_sections": draft.total_sections,
                "validation_confidence": validation.confidence,
                "validation_errors": validation.error_count,
                "validation_warnings": validation.warning_count,
            },
        )

        logger.info(
            "Build-structure complete",
            parts=draft.total_parts,
            chapters=draft.total_chapters,
            sections=draft.total_sections,
            confidence=f"{validation.confidence:.2f}",
            cost=f"${total_cost:.4f}",
        )

        return {
            "status": "success",
            "total_parts": draft.total_parts,
            "total_chapters": draft.total_chapters,
            "total_sections": draft.total_sections,
            "validation_confidence": validation.confidence,
            "validation_errors": validation.error_count,
            "validation_warnings": validation.warning_count,
            "cost_usd": total_cost,
        }
