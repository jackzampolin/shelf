"""
Book metadata extraction and enrichment tools.

Usage:
    from tools.metadata import extract_metadata, enrich_from_open_library

    # Extract from OCR using web-search LLM
    metadata = extract_metadata(book_storage)

    # Enrich with Open Library data
    metadata = enrich_from_open_library(book_storage, metadata)

    # Save to book's metadata.json
    save_metadata(book_storage, metadata)
"""

from .schemas import (
    BookMetadata,
    BookIdentifiers,
    Contributor,
    METADATA_EXTRACTION_SCHEMA,
)
from .extract import (
    extract_metadata,
    save_metadata,
)
from .enrich import (
    enrich_from_open_library,
    save_enriched_metadata,
)


__all__ = [
    "BookMetadata",
    "BookIdentifiers",
    "Contributor",
    "METADATA_EXTRACTION_SCHEMA",
    "extract_metadata",
    "save_metadata",
    "enrich_from_open_library",
    "save_enriched_metadata",
]
