import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import artifact_tracker
from infra.config import Config

from .schemas import CommonStructureOutput, BookMetadata, PageReference, StructureEntry, SectionText
from .tools import (
    detect_boundaries,
    classify_front_back_matter_from_entries,
    extract_headings_from_labels,
    reconcile_toc_with_headings,
    build_structure_entries,
    calculate_hierarchy_stats,
    extract_section_text,
    polish_section_text,
    classify_entries,
    EntryForClassification,
)


class CommonStructureStage(BaseStage):
    name = "common-structure"
    dependencies = ["link-toc", "label-structure", "ocr-pages"]

    @classmethod
    def default_kwargs(cls, **overrides):
        kwargs = {'model': None, 'skip_polish': False}
        if 'model' in overrides and overrides['model']:
            kwargs['model'] = overrides['model']
        if 'skip_polish' in overrides:
            kwargs['skip_polish'] = overrides['skip_polish']
        return kwargs

    def __init__(
        self,
        storage: BookStorage,
        model: Optional[str] = None,
        skip_polish: bool = False
    ):
        super().__init__(storage)
        self.model = model or Config.vision_model_primary
        self.skip_polish = skip_polish

        def extract_structure(tracker, **kwargs):
            return self._extract_structure(tracker)

        self.status_tracker = artifact_tracker(
            stage_storage=self.stage_storage,
            phase_name="extract_structure",
            artifact_filename="structure.json",
            run_fn=extract_structure,
        )


    def _extract_structure(self, tracker) -> Dict[str, Any]:
        storage = tracker.storage
        logger = tracker.logger

        start_time = datetime.now(timezone.utc)

        total_pages = storage.load_metadata().get("total_pages", 0)
        if not total_pages:
            raise ValueError("total_pages not found in book metadata")

        logger.info(f"Reconciling structure for {total_pages} pages")

        logger.info("Phase 1: Top-down - detecting ToC boundaries...")
        toc_boundaries = detect_boundaries(storage, logger, total_pages)

        if not toc_boundaries:
            raise ValueError("No ToC boundaries detected - check link-toc output")

        logger.info(f"✓ Found {len(toc_boundaries)} ToC entries")

        logger.info("Phase 2: Bottom-up - extracting headings from pages...")
        headings = extract_headings_from_labels(storage, logger, total_pages)
        logger.info(f"✓ Found {len(headings)} headings in label-structure")

        logger.info("Phase 3: Reconciling ToC with observed headings...")
        reconciled_boundaries = reconcile_toc_with_headings(
            toc_boundaries, headings, logger
        )
        logger.info(f"✓ Reconciled {len(reconciled_boundaries)} boundaries")

        logger.info("Phase 4: Building hierarchical structure...")
        structure_entries = build_structure_entries(reconciled_boundaries, logger)

        stats = calculate_hierarchy_stats(structure_entries)
        logger.info(
            f"✓ Built hierarchy: {stats['total_parts']} parts, "
            f"{stats['total_chapters']} chapters, {stats['total_sections']} sections"
        )

        logger.info("Phase 5: Classifying entries as front/body/back matter (LLM)...")
        entries_for_classification = [
            EntryForClassification(
                entry_id=entry.entry_id,
                title=entry.title,
                position=i + 1,
                total_entries=len(structure_entries),
                scan_page_start=entry.scan_page_start
            )
            for i, entry in enumerate(structure_entries)
        ]

        classifications = classify_entries(tracker, entries_for_classification, self.model)

        for entry in structure_entries:
            if entry.entry_id in classifications:
                entry.matter_type = classifications[entry.entry_id]

        matter_counts = {"front_matter": 0, "body": 0, "back_matter": 0}
        for entry in structure_entries:
            matter_counts[entry.matter_type] += 1
        logger.info(
            f"✓ Classified: {matter_counts['front_matter']} front, "
            f"{matter_counts['body']} body, {matter_counts['back_matter']} back"
        )

        logger.info("Phase 6: Building page references...")
        page_references = self._build_page_references(storage, total_pages)
        logger.info(f"✓ Built {len(page_references)} page references")

        logger.info("Phase 7: Computing front/back matter page lists...")
        front_matter, back_matter = classify_front_back_matter_from_entries(structure_entries, total_pages)
        logger.info(
            f"✓ Front matter: {len(front_matter)} pages, Back matter: {len(back_matter)} pages"
        )

        logger.info("Phase 8: Extracting text content for each section...")
        total_words = 0
        for entry in structure_entries:
            section_text = extract_section_text(
                storage, logger,
                entry.scan_page_start,
                entry.scan_page_end
            )
            entry.content = section_text
            total_words += section_text.word_count

        logger.info(f"✓ Extracted text for {len(structure_entries)} sections ({total_words:,} words)")

        if not self.skip_polish:
            logger.info("Phase 9: LLM polish (generating edits)...")
            total_edits = 0
            for entry in structure_entries:
                if entry.content and entry.content.mechanical_text:
                    entry.content = polish_section_text(
                        tracker, entry.title, entry.content, self.model
                    )
                    total_edits += len(entry.content.edits_applied)

            logger.info(f"✓ Applied {total_edits} edits across {len(structure_entries)} sections")
        else:
            logger.info("Phase 9: Skipping LLM polish (--skip-polish)")
            for entry in structure_entries:
                if entry.content:
                    entry.content.final_text = entry.content.mechanical_text

        metadata = self._build_metadata(storage, total_pages)

        end_time = datetime.now(timezone.utc)
        processing_time = (end_time - start_time).total_seconds()

        # Calculate total cost from metrics
        total_cost = tracker.metrics_manager.get_total_cost() if hasattr(tracker, 'metrics_manager') else 0.0

        output = CommonStructureOutput(
            metadata=metadata,
            page_references=page_references,
            entries=structure_entries,
            front_matter_pages=front_matter,
            back_matter_pages=back_matter,
            total_entries=stats["total_entries"],
            total_chapters=stats["total_chapters"],
            total_parts=stats["total_parts"],
            total_sections=stats["total_sections"],
            extracted_at=end_time.isoformat(),
            cost_usd=total_cost,
            processing_time_seconds=processing_time
        )

        logger.info("Saving structure.json...")
        structure_path = tracker.phase_dir / "structure.json"
        with open(structure_path, "w") as f:
            json.dump(output.model_dump(), f, indent=2)

        logger.info(f"✓ Structure extraction complete in {processing_time:.1f}s")
        logger.info(f"  → {stats['total_entries']} entries, {total_words:,} words, ${total_cost:.4f}")

        return {"status": "success"}

    def _build_page_references(self, storage, total_pages: int) -> list[PageReference]:
        from .schemas import PageReference

        page_refs = []
        label_structure_storage = storage.stage("label-structure")

        for page_num in range(1, total_pages + 1):
            # Load from unified subdirectory where page numbers are stored
            page_data = label_structure_storage.load_file(f"unified/page_{page_num:04d}.json")

            if not page_data:
                page_refs.append(PageReference(
                    scan_page=page_num,
                    printed_page=None,
                    numbering_style="none"
                ))
                continue

            page_num_data = page_data.get("page_number", {})
            printed_page = page_num_data.get("number") if page_num_data.get("present") else None

            numbering_style = "none"
            if printed_page:
                if printed_page.isdigit():
                    numbering_style = "arabic"
                elif all(c.lower() in "ivxlcdm" for c in printed_page.lower()):
                    numbering_style = "roman"
                elif printed_page.isalpha():
                    numbering_style = "letter"

            page_refs.append(PageReference(
                scan_page=page_num,
                printed_page=printed_page,
                numbering_style=numbering_style
            ))

        return page_refs

    def _build_metadata(self, storage, total_pages: int) -> BookMetadata:
        scan_id = storage.scan_id

        metadata_file = storage.book_dir / "metadata.json"
        existing_metadata = {}
        if metadata_file.exists():
            with open(metadata_file, "r") as f:
                existing_metadata = json.load(f)

        return BookMetadata(
            scan_id=scan_id,
            title=existing_metadata.get("title"),
            author=existing_metadata.get("author"),
            publisher=existing_metadata.get("publisher"),
            publication_year=existing_metadata.get("publication_year"),
            language=existing_metadata.get("language", "en"),
            total_scan_pages=total_pages
        )


__all__ = [
    "CommonStructureStage",
    "CommonStructureOutput",
    "BookMetadata",
    "PageReference",
    "StructureEntry",
]
