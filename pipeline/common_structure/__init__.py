import json
from datetime import datetime, timezone
from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker

from .schemas import CommonStructureOutput, BookMetadata, PageReference, StructureEntry
from .tools import (
    detect_boundaries,
    classify_front_back_matter,
    extract_headings_from_labels,
    reconcile_toc_with_headings,
    build_structure_entries,
    calculate_hierarchy_stats
)


class CommonStructureStage(BaseStage):
    name = "common-structure"
    dependencies = ["link-toc", "label-structure"]

    @classmethod
    def default_kwargs(cls, **overrides):
        return {}

    def __init__(self, storage: BookStorage):
        super().__init__(storage)

        self.status_tracker = MultiPhaseStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            phases=[{"name": "extract_structure", "artifact": "structure.json"}]
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        structure_path = self.stage_storage.output_dir / "structure.json"
        if structure_path.exists():
            self.logger.info("✓ Structure already extracted")
            return {"status": "success"}

        start_time = datetime.now(timezone.utc)

        total_pages = self.storage.metadata.get("total_pages", 0)
        if not total_pages:
            raise ValueError("total_pages not found in book metadata")

        self.logger.info(f"Reconciling structure for {total_pages} pages")

        self.logger.info("Phase 1: Top-down - detecting ToC boundaries...")
        toc_boundaries = detect_boundaries(self.storage, self.logger, total_pages)

        if not toc_boundaries:
            raise ValueError("No ToC boundaries detected - check link-toc output")

        self.logger.info(f"✓ Found {len(toc_boundaries)} ToC entries")

        self.logger.info("Phase 2: Bottom-up - extracting headings from pages...")
        headings = extract_headings_from_labels(self.storage, self.logger, total_pages)
        self.logger.info(f"✓ Found {len(headings)} headings in label-structure")

        self.logger.info("Phase 3: Reconciling ToC with observed headings...")
        reconciled_boundaries = reconcile_toc_with_headings(
            toc_boundaries, headings, self.logger
        )
        self.logger.info(f"✓ Reconciled {len(reconciled_boundaries)} boundaries")

        self.logger.info("Phase 4: Building hierarchical structure...")
        structure_entries = build_structure_entries(reconciled_boundaries, self.logger)

        stats = calculate_hierarchy_stats(structure_entries)
        self.logger.info(
            f"✓ Built hierarchy: {stats['total_parts']} parts, "
            f"{stats['total_chapters']} chapters, {stats['total_sections']} sections"
        )

        self.logger.info("Phase 5: Building page references...")
        page_references = self._build_page_references(total_pages)
        self.logger.info(f"✓ Built {len(page_references)} page references")

        self.logger.info("Phase 6: Classifying front/back matter...")
        front_matter, back_matter = classify_front_back_matter(reconciled_boundaries, total_pages)
        self.logger.info(
            f"✓ Front matter: {len(front_matter)} pages, Back matter: {len(back_matter)} pages"
        )

        metadata = self._build_metadata(total_pages)

        end_time = datetime.now(timezone.utc)
        processing_time = (end_time - start_time).total_seconds()

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
            cost_usd=0.0,
            processing_time_seconds=processing_time
        )

        self.logger.info("Saving structure.json...")
        with open(structure_path, "w") as f:
            json.dump(output.model_dump(), f, indent=2)

        self.logger.info(f"✓ Structure reconciliation complete in {processing_time:.1f}s")
        self.logger.info(f"  → {stats['total_entries']} entries, {len(page_references)} pages")

        return {"status": "success"}

    def _build_page_references(self, total_pages: int) -> list[PageReference]:
        from .schemas import PageReference

        page_refs = []
        label_structure_storage = self.storage.stage("label-structure")

        for page_num in range(1, total_pages + 1):
            page_data = label_structure_storage.load_page(page_num)

            if not page_data:
                page_refs.append(PageReference(
                    scan_page=page_num,
                    printed_page=None,
                    numbering_style="none"
                ))
                continue

            page_num_data = page_data.get("page_number", {})
            printed_page = page_num_data.get("number")

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

    def _build_metadata(self, total_pages: int) -> BookMetadata:
        scan_id = self.storage.scan_id

        metadata_file = self.storage.root_dir / "metadata.json"
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
