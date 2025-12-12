"""
Metadata extraction processor for ocr-pages stage.

Uses web-search LLM to extract book metadata from OCR output,
then enriches via Open Library API.
"""

from typing import Dict, Any
from pathlib import Path

from infra.pipeline.status import PhaseStatusTracker
from tools.metadata import extract_metadata, enrich_from_open_library, save_metadata


MARKER_FILENAME = "metadata_extracted.json"


def create_metadata_tracker(stage_storage, model: str = None):
    """Create tracker for metadata extraction phase."""
    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name="metadata",
        discoverer=lambda phase_dir: [MARKER_FILENAME],
        output_path_fn=lambda item, phase_dir: phase_dir / item,
        run_fn=process_metadata,
        use_subdir=False,
        run_kwargs={"model": model},
        description="Extract book metadata using AI with web search",
    )


def process_metadata(tracker: PhaseStatusTracker, **kwargs) -> Dict[str, Any]:
    """
    Extract and enrich book metadata.

    1. Uses web-search LLM to identify book from OCR output
    2. Enriches with Open Library data (if ISBN found)
    3. Saves to book's metadata.json
    4. Creates marker file to track completion
    """
    model = kwargs.get("model")
    book_storage = tracker.storage

    tracker.logger.info("Starting metadata extraction...")

    # Step 1: Extract metadata using web-search LLM
    try:
        metadata = extract_metadata(
            book_storage,
            model=model,
            max_pages=20,
        )
        tracker.logger.info(f"Extracted: {metadata.title} by {', '.join(metadata.authors)}")

        if metadata.identifiers.isbn_13 or metadata.identifiers.isbn_10:
            isbn = metadata.identifiers.isbn_13 or metadata.identifiers.isbn_10
            tracker.logger.info(f"Found ISBN: {isbn}")

    except Exception as e:
        tracker.logger.error(f"Extraction failed: {e}")
        raise

    # Step 2: Enrich with Open Library (if we have title or ISBN)
    try:
        if metadata.title or metadata.identifiers.isbn_13 or metadata.identifiers.isbn_10:
            enriched = enrich_from_open_library(book_storage, metadata)
            if enriched.cover_url:
                tracker.logger.info(f"Enriched with Open Library data (cover found)")
            if enriched.subjects_lcsh:
                tracker.logger.info(f"Added {len(enriched.subjects_lcsh)} LCSH subjects")
            metadata = enriched
    except Exception as e:
        tracker.logger.warning(f"Open Library enrichment failed: {e}")
        # Continue with unenriched metadata

    # Step 3: Save to book's metadata.json
    save_metadata(book_storage, metadata)
    tracker.logger.info(f"Saved metadata to {book_storage.metadata_file}")

    # Step 4: Create marker file to track completion
    marker_path = tracker.stage_storage.stage_dir / MARKER_FILENAME
    import json
    with open(marker_path, "w") as f:
        json.dump({
            "status": "completed",
            "title": metadata.title,
            "authors": metadata.authors,
            "isbn": metadata.identifiers.isbn_13 or metadata.identifiers.isbn_10,
            "confidence": metadata.extraction_confidence,
        }, f, indent=2)

    return {
        "status": "completed",
        "title": metadata.title,
        "authors": metadata.authors,
    }
