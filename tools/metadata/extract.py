"""
Extract book metadata using web-search-enabled LLM.

Uses the first ~20 pages of OCR output + web search to identify
the book and extract structured metadata.
"""

import json
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from infra.config import get_library_config, get_api_key
from infra.llm import LLMClient
from infra.pipeline.storage import BookStorage
from .schemas import BookMetadata, BookIdentifiers, Contributor, METADATA_EXTRACTION_SCHEMA


EXTRACTION_SYSTEM_PROMPT = """You are a book metadata extraction assistant with web search capability.

Given OCR text from the first pages of a scanned book, identify the book and extract accurate metadata.

INSTRUCTIONS:
1. Use the title page, copyright page, and any front matter to identify the book
2. Use web search to verify the book's identity and find accurate metadata
3. Look for ISBN, LCCN, publisher, publication year on the copyright page
4. If you can identify the book online, use the official metadata from sources like:
   - Open Library, WorldCat, Library of Congress, Amazon, Goodreads
5. Generate a brief description if not found in the text

IMPORTANT:
- Prefer official/authoritative metadata over OCR-extracted text
- Include ALL authors if multiple
- Use ISO 639-1 language codes (en, es, fr, de, etc.)
- Set confidence based on how certain you are of the identification"""


EXTRACTION_USER_PROMPT = """Here is OCR text from the first pages of a scanned book:

<book_text>
{book_text}
</book_text>

Please identify this book and extract its metadata. Use web search to verify and find accurate information."""


def extract_metadata(
    storage: BookStorage,
    model: Optional[str] = None,
    max_pages: int = 20,
) -> BookMetadata:
    """
    Extract book metadata from OCR output using web-search LLM.

    Args:
        storage: BookStorage instance for the book
        model: LLM model to use (defaults to config, should support web search)
        max_pages: Number of pages to analyze (default 20)

    Returns:
        BookMetadata with extracted information
    """
    # Get model from config if not specified
    if model is None:
        config = get_library_config()
        # Use default LLM provider
        default_provider = config.defaults.llm_provider
        provider = config.get_llm_provider(default_provider)
        if provider:
            # Add :online suffix for web search capability
            model = f"{provider.model}:online"
        else:
            model = "x-ai/grok-2-1212:online"

    # Load OCR text from first N pages
    book_text = _load_first_pages(storage, max_pages)

    if not book_text:
        raise ValueError(f"No OCR output found for {storage.scan_id}")

    # Call LLM with web search enabled
    client = LLMClient()

    result = client.call(
        model=model,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": EXTRACTION_USER_PROMPT.format(book_text=book_text)},
        ],
        response_format=METADATA_EXTRACTION_SCHEMA,
        temperature=0.1,
        max_tokens=2048,
        timeout=120,
    )

    if not result.success:
        raise RuntimeError(f"Metadata extraction failed: {result.error_message}")

    if not result.parsed_json:
        raise RuntimeError("LLM returned empty response")

    # Convert to BookMetadata
    data = result.parsed_json
    return _build_metadata(data, model)


def _load_first_pages(storage: BookStorage, max_pages: int) -> str:
    """Load OCR text from first N pages."""
    ocr_stage = storage.stage("ocr-pages")

    # Try blend first, fall back to mistral
    subdirs = ["blend", "mistral", "paddle"]
    text_parts = []

    for subdir in subdirs:
        for page_num in range(1, max_pages + 1):
            try:
                data = ocr_stage.load_page(page_num, subdir=subdir)
                text = data.get("markdown") or data.get("text", "")
                if text:
                    text_parts.append(f"--- Page {page_num} ---\n{text}")
            except FileNotFoundError:
                continue

        if text_parts:
            break

    return "\n\n".join(text_parts)


def _build_metadata(data: Dict[str, Any], model: str) -> BookMetadata:
    """Convert LLM response to BookMetadata."""
    # Parse identifiers
    identifiers = BookIdentifiers()
    if data.get("isbn"):
        isbn = data["isbn"].replace("-", "").replace(" ", "")
        if len(isbn) == 10:
            identifiers.isbn_10 = isbn
        elif len(isbn) == 13:
            identifiers.isbn_13 = isbn
    if data.get("lccn"):
        identifiers.lccn = data["lccn"]

    # Parse contributors
    contributors = []
    for c in data.get("contributors", []):
        contributors.append(Contributor(name=c["name"], role=c["role"]))

    return BookMetadata(
        title=data["title"],
        subtitle=data.get("subtitle"),
        authors=data.get("authors", []),
        identifiers=identifiers,
        language=data.get("language", "en"),
        publisher=data.get("publisher"),
        publication_year=data.get("publication_year"),
        description=data.get("description"),
        subjects=data.get("subjects", []),
        contributors=contributors,
        extraction_source=f"llm:{model}",
        extraction_confidence=data.get("confidence"),
        extracted_at=datetime.now(),
    )


def save_metadata(storage: BookStorage, metadata: BookMetadata) -> None:
    """Save extracted metadata to book's metadata.json."""
    # Load existing metadata
    try:
        existing = storage.load_metadata()
    except FileNotFoundError:
        existing = {}

    # Merge with extracted metadata
    extracted = metadata.model_dump(exclude_none=True)

    # Convert datetime to ISO strings
    if "extracted_at" in extracted:
        extracted["extracted_at"] = extracted["extracted_at"].isoformat()
    if "enriched_at" in extracted:
        extracted["enriched_at"] = extracted["enriched_at"].isoformat()

    # Update existing metadata
    existing.update({
        "title": extracted.get("title", existing.get("title")),
        "author": ", ".join(extracted.get("authors", [])) or existing.get("author"),
        "authors": extracted.get("authors", existing.get("authors", [])),
        "isbn": extracted.get("identifiers", {}).get("isbn_13") or
                extracted.get("identifiers", {}).get("isbn_10") or
                existing.get("isbn"),
        "identifiers": extracted.get("identifiers", existing.get("identifiers", {})),
        "publisher": extracted.get("publisher", existing.get("publisher")),
        "publication_year": extracted.get("publication_year", existing.get("publication_year")),
        "language": extracted.get("language", existing.get("language")),
        "description": extracted.get("description", existing.get("description")),
        "subjects": extracted.get("subjects", existing.get("subjects", [])),
        "contributors": extracted.get("contributors", existing.get("contributors", [])),
        "extraction_source": extracted.get("extraction_source"),
        "extraction_confidence": extracted.get("extraction_confidence"),
        "extracted_at": extracted.get("extracted_at"),
    })

    storage.save_metadata(existing)
