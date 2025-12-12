"""
Enrich book metadata using Open Library API.

Fetches additional data based on ISBN or title/author search.
"""

import requests
from datetime import datetime
from typing import Optional, Dict, Any, List

from infra.pipeline.storage import BookStorage
from .schemas import BookMetadata, BookIdentifiers


OPEN_LIBRARY_API = "https://openlibrary.org"
OPEN_LIBRARY_COVERS = "https://covers.openlibrary.org"


def enrich_from_open_library(
    storage: BookStorage,
    metadata: Optional[BookMetadata] = None,
) -> BookMetadata:
    """
    Enrich book metadata using Open Library API.

    Looks up by ISBN first, falls back to title/author search.

    Args:
        storage: BookStorage instance
        metadata: Existing metadata (loads from storage if not provided)

    Returns:
        Enriched BookMetadata
    """
    # Load existing metadata if not provided
    if metadata is None:
        try:
            data = storage.load_metadata()
            metadata = _metadata_from_dict(data)
        except FileNotFoundError:
            raise ValueError(f"No metadata found for {storage.scan_id}")

    # Try ISBN lookup first
    isbn = metadata.identifiers.isbn_13 or metadata.identifiers.isbn_10
    if isbn:
        ol_data = _lookup_by_isbn(isbn)
        if ol_data:
            return _merge_open_library_data(metadata, ol_data)

    # Fall back to title/author search
    if metadata.title:
        ol_data = _search_by_title_author(
            metadata.title,
            metadata.authors[0] if metadata.authors else None
        )
        if ol_data:
            return _merge_open_library_data(metadata, ol_data)

    # No enrichment found
    return metadata


def _lookup_by_isbn(isbn: str) -> Optional[Dict[str, Any]]:
    """Look up book by ISBN using Open Library Books API."""
    url = f"{OPEN_LIBRARY_API}/isbn/{isbn}.json"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            edition_data = response.json()

            # Get work data for subjects
            work_key = None
            if edition_data.get("works"):
                work_key = edition_data["works"][0]["key"]
                work_data = _fetch_work(work_key)
            else:
                work_data = {}

            return {
                "edition": edition_data,
                "work": work_data,
                "source": f"isbn:{isbn}",
            }
    except Exception:
        pass

    return None


def _search_by_title_author(title: str, author: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Search Open Library by title and author."""
    params = {"title": title, "limit": 5}
    if author:
        params["author"] = author

    url = f"{OPEN_LIBRARY_API}/search.json"

    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("docs"):
                # Get first result
                doc = data["docs"][0]

                # Fetch edition and work details
                edition_key = doc.get("cover_edition_key") or (
                    doc.get("edition_key", [None])[0]
                )
                work_key = doc.get("key")

                edition_data = _fetch_edition(edition_key) if edition_key else {}
                work_data = _fetch_work(work_key) if work_key else {}

                return {
                    "search": doc,
                    "edition": edition_data,
                    "work": work_data,
                    "source": f"search:{title}",
                }
    except Exception:
        pass

    return None


def _fetch_work(work_key: str) -> Dict[str, Any]:
    """Fetch work details from Open Library."""
    if not work_key.startswith("/works/"):
        work_key = f"/works/{work_key}"

    url = f"{OPEN_LIBRARY_API}{work_key}.json"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass

    return {}


def _fetch_edition(edition_key: str) -> Dict[str, Any]:
    """Fetch edition details from Open Library."""
    if not edition_key.startswith("/books/"):
        edition_key = f"/books/{edition_key}"

    url = f"{OPEN_LIBRARY_API}{edition_key}.json"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass

    return {}


def _merge_open_library_data(metadata: BookMetadata, ol_data: Dict[str, Any]) -> BookMetadata:
    """Merge Open Library data into existing metadata."""
    edition = ol_data.get("edition", {})
    work = ol_data.get("work", {})
    search = ol_data.get("search", {})

    # Get cover URL
    cover_id = edition.get("covers", [None])[0] or search.get("cover_i")
    cover_url = None
    if cover_id:
        cover_url = f"{OPEN_LIBRARY_COVERS}/b/id/{cover_id}-L.jpg"

    # Get subjects from work
    subjects_lcsh = []
    for subject in work.get("subjects", []):
        if isinstance(subject, str):
            subjects_lcsh.append(subject)
        elif isinstance(subject, dict):
            subjects_lcsh.append(subject.get("name", ""))

    # Also add from search results
    for subject in search.get("subject", [])[:10]:
        if subject not in subjects_lcsh:
            subjects_lcsh.append(subject)

    # Get first publish year
    first_publish_year = search.get("first_publish_year") or work.get("first_publish_date")
    if isinstance(first_publish_year, str):
        try:
            first_publish_year = int(first_publish_year[:4])
        except (ValueError, TypeError):
            first_publish_year = None

    # Get Open Library ID
    ol_id = None
    if edition.get("key"):
        ol_id = edition["key"].replace("/books/", "")
    elif work.get("key"):
        ol_id = work["key"].replace("/works/", "")

    # Update identifiers
    identifiers = metadata.identifiers.model_copy()
    if ol_id:
        identifiers.open_library_id = ol_id

    # Get ISBNs if we didn't have them
    if not identifiers.isbn_13 and edition.get("isbn_13"):
        identifiers.isbn_13 = edition["isbn_13"][0]
    if not identifiers.isbn_10 and edition.get("isbn_10"):
        identifiers.isbn_10 = edition["isbn_10"][0]
    if not identifiers.lccn and edition.get("lccn"):
        identifiers.lccn = edition["lccn"][0]
    if not identifiers.oclc and edition.get("oclc_numbers"):
        identifiers.oclc = edition["oclc_numbers"][0]

    # Get description if we don't have one
    description = metadata.description
    if not description:
        desc = work.get("description") or edition.get("description")
        if isinstance(desc, dict):
            description = desc.get("value", "")
        elif isinstance(desc, str):
            description = desc

    # Build updated metadata
    return BookMetadata(
        title=metadata.title,
        subtitle=metadata.subtitle,
        authors=metadata.authors,
        identifiers=identifiers,
        language=metadata.language,
        publisher=metadata.publisher or _get_publisher(edition),
        publication_year=metadata.publication_year or _get_publish_year(edition),
        description=description,
        subjects=metadata.subjects if metadata.subjects else subjects_lcsh[:10],
        contributors=metadata.contributors,
        cover_url=cover_url,
        subjects_lcsh=subjects_lcsh[:20],
        first_publish_year=first_publish_year,
        extraction_source=metadata.extraction_source,
        extraction_confidence=metadata.extraction_confidence,
        extracted_at=metadata.extracted_at,
        enriched_at=datetime.now(),
    )


def _get_publisher(edition: Dict[str, Any]) -> Optional[str]:
    """Extract publisher from edition data."""
    publishers = edition.get("publishers", [])
    if publishers:
        return publishers[0]
    return None


def _get_publish_year(edition: Dict[str, Any]) -> Optional[int]:
    """Extract publish year from edition data."""
    publish_date = edition.get("publish_date")
    if publish_date:
        try:
            # Try to extract year from various formats
            import re
            match = re.search(r'\b(19|20)\d{2}\b', publish_date)
            if match:
                return int(match.group())
        except (ValueError, TypeError):
            pass
    return None


def _metadata_from_dict(data: Dict[str, Any]) -> BookMetadata:
    """Convert dict to BookMetadata."""
    identifiers = BookIdentifiers()
    if data.get("identifiers"):
        identifiers = BookIdentifiers(**data["identifiers"])
    elif data.get("isbn"):
        isbn = data["isbn"]
        if len(isbn) == 10:
            identifiers.isbn_10 = isbn
        elif len(isbn) == 13:
            identifiers.isbn_13 = isbn

    return BookMetadata(
        title=data.get("title", "Unknown"),
        subtitle=data.get("subtitle"),
        authors=data.get("authors", []),
        identifiers=identifiers,
        language=data.get("language", "en"),
        publisher=data.get("publisher"),
        publication_year=data.get("publication_year"),
        description=data.get("description"),
        subjects=data.get("subjects", []),
    )


def save_enriched_metadata(storage: BookStorage, metadata: BookMetadata) -> None:
    """Save enriched metadata to book's metadata.json."""
    from .extract import save_metadata
    save_metadata(storage, metadata)
