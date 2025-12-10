"""Phase 3: Merge all entry files into final structure.json."""

import json
from datetime import datetime, timezone
from pathlib import Path

from infra.pipeline.status import artifact_tracker
from infra.pipeline.storage.stage_storage import StageStorage

from ..tools import classify_front_back_matter_from_entries
from ..schemas import StructureEntry, SectionText, CommonStructureOutput, BookMetadata, PageReference


def create_merge_tracker(stage_storage: StageStorage):
    def merge_entries(tracker):
        storage = tracker.storage
        logger = tracker.logger

        # Load skeleton
        skeleton = storage.stage("common-structure").load_file("build_structure/structure_skeleton.json")
        total_pages = skeleton.get("total_pages", 0)
        stats = skeleton.get("stats", {})
        entries_data = skeleton.get("entries", [])

        # Load polished entries
        polish_dir = storage.stage("common-structure").output_dir / "polish_entries"

        entries = []
        for entry_data in entries_data:
            entry = StructureEntry(**entry_data)
            entry_file = polish_dir / f"{entry.entry_id}.json"

            if entry_file.exists():
                with open(entry_file) as f:
                    polished = json.load(f)
                    if polished.get("content"):
                        entry.content = SectionText(**polished["content"])

            entries.append(entry)

        # Build page references
        page_references = _build_page_references(storage, logger, total_pages)

        # Classify front/back matter from entries
        front_matter_pages, back_matter_pages = classify_front_back_matter_from_entries(entries, total_pages)

        # Build metadata
        metadata = _build_metadata(storage, total_pages)

        # Get cost from metrics
        total_cost = tracker.metrics_manager.get_total_cost() if hasattr(tracker, 'metrics_manager') else 0.0

        # Build final output
        output = CommonStructureOutput(
            metadata=metadata,
            page_references=page_references,
            entries=entries,
            front_matter_pages=front_matter_pages,
            back_matter_pages=back_matter_pages,
            total_entries=stats.get("total_entries", len(entries)),
            total_chapters=stats.get("total_chapters", 0),
            total_parts=stats.get("total_parts", 0),
            total_sections=stats.get("total_sections", 0),
            extracted_at=datetime.now(timezone.utc).isoformat(),
            cost_usd=total_cost,
            processing_time_seconds=0.0,  # Will be set by stage runner
        )

        # Save structure.json
        output_path = tracker.phase_dir / "structure.json"
        with open(output_path, "w") as f:
            f.write(output.model_dump_json(indent=2))

        logger.info(f"Merged {len(entries)} entries into structure.json")
        return {"status": "success", "entry_count": len(entries)}

    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="merge",
        artifact_filename="structure.json",
        run_fn=merge_entries,
        use_subdir=True,
    )


def _build_page_references(storage, logger, total_pages):
    """Build mapping from scan page to printed page."""
    page_references = []
    label_storage = storage.stage("label-structure")

    for page_num in range(1, total_pages + 1):
        try:
            page_data = label_storage.load_file(f"unified/page_{page_num:04d}.json")
            if page_data:
                page_num_data = page_data.get("page_number", {})
                if page_num_data.get("present"):
                    printed = page_num_data.get("number")
                    if printed:
                        page_references.append(
                            PageReference(scan_page=page_num, printed_page=str(printed))
                        )
        except Exception:
            continue

    return page_references


def _build_metadata(storage, total_pages: int) -> BookMetadata:
    """Build book metadata from storage."""
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
