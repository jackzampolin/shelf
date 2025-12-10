"""Phase 1: Build structure skeleton (no text content yet)."""

import json
from infra.pipeline.status import artifact_tracker
from infra.pipeline.storage.stage_storage import StageStorage

from ..tools import (
    detect_boundaries,
    extract_headings_from_labels,
    reconcile_toc_with_headings,
    build_structure_entries,
    calculate_hierarchy_stats,
    classify_entries,
    EntryForClassification,
)


def create_build_tracker(stage_storage: StageStorage, model: str):
    def build_structure(tracker, model=model):
        storage = tracker.storage
        logger = tracker.logger

        total_pages = storage.load_metadata().get("total_pages", 0)
        if not total_pages:
            raise ValueError("total_pages not found in book metadata")

        logger.info(f"Building structure skeleton for {total_pages} pages")

        # Phase 1: Detect ToC boundaries
        logger.info("Step 1: Detecting ToC boundaries...")
        toc_boundaries = detect_boundaries(storage, logger, total_pages)
        if not toc_boundaries:
            raise ValueError("No ToC boundaries detected - check link-toc output")
        logger.info(f"Found {len(toc_boundaries)} ToC entries")

        # Phase 2: Extract headings from labels
        logger.info("Step 2: Extracting headings from labels...")
        headings = extract_headings_from_labels(storage, logger, total_pages)
        logger.info(f"Found {len(headings)} headings")

        # Phase 3: Reconcile
        logger.info("Step 3: Reconciling ToC with headings...")
        reconciled = reconcile_toc_with_headings(toc_boundaries, headings, logger)
        logger.info(f"Reconciled {len(reconciled)} boundaries")

        # Phase 4: Build hierarchy
        logger.info("Step 4: Building hierarchy...")
        entries = build_structure_entries(reconciled, logger)
        stats = calculate_hierarchy_stats(entries)
        logger.info(f"Built {stats['total_entries']} entries")

        # Phase 5: Classify matter types (LLM call)
        logger.info("Step 5: Classifying matter types (LLM)...")
        entries_for_classification = [
            EntryForClassification(
                entry_id=entry.entry_id,
                title=entry.title,
                position=i + 1,
                total_entries=len(entries),
                scan_page_start=entry.scan_page_start
            )
            for i, entry in enumerate(entries)
        ]
        classifications = classify_entries(tracker, entries_for_classification, model)
        for entry in entries:
            if entry.entry_id in classifications:
                entry.matter_type = classifications[entry.entry_id]

        # Build skeleton output (entries without content)
        skeleton = {
            "total_pages": total_pages,
            "entries": [entry.model_dump() for entry in entries],
            "stats": stats,
        }

        # Save skeleton
        skeleton_path = tracker.phase_dir / "structure_skeleton.json"
        with open(skeleton_path, "w") as f:
            json.dump(skeleton, f, indent=2)

        logger.info(f"Saved structure skeleton with {len(entries)} entries")
        return {"status": "success", "entry_count": len(entries)}

    return artifact_tracker(
        stage_storage=stage_storage,
        phase_name="build_structure",
        artifact_filename="structure_skeleton.json",
        run_fn=build_structure,
        use_subdir=True,
        run_kwargs={"model": model},
    )
