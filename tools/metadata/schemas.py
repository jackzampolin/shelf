"""
Book metadata schemas.

Defines the structure for extracted and enriched book metadata.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class BookIdentifiers(BaseModel):
    """Standard book identifiers."""
    isbn_10: Optional[str] = Field(None, description="10-digit ISBN")
    isbn_13: Optional[str] = Field(None, description="13-digit ISBN")
    lccn: Optional[str] = Field(None, description="Library of Congress Control Number")
    oclc: Optional[str] = Field(None, description="OCLC number")
    open_library_id: Optional[str] = Field(None, description="Open Library work/edition ID")


class Contributor(BaseModel):
    """A contributor to the book (author, editor, translator, etc.)."""
    name: str
    role: str = "author"  # author, editor, translator, illustrator, etc.


class BookMetadata(BaseModel):
    """
    Complete book metadata.

    Tier 1 (Essential - ePub required):
    - title, authors, identifiers, language

    Tier 2 (Useful):
    - publisher, publication_year, description, subjects, contributors

    Tier 4 (Enrichment from Open Library):
    - cover_url, subjects_lcsh, first_publish_year, related_works
    """
    # Tier 1: Essential
    title: str = Field(..., description="Official book title")
    subtitle: Optional[str] = Field(None, description="Book subtitle if any")
    authors: List[str] = Field(default_factory=list, description="Primary author(s)")
    identifiers: BookIdentifiers = Field(default_factory=BookIdentifiers)
    language: str = Field("en", description="ISO 639-1 language code")

    # Tier 2: Useful
    publisher: Optional[str] = Field(None, description="Publishing house")
    publication_year: Optional[int] = Field(None, description="Year of publication")
    description: Optional[str] = Field(None, description="Book summary/description")
    subjects: List[str] = Field(default_factory=list, description="Subject keywords/topics")
    contributors: List[Contributor] = Field(default_factory=list, description="Other contributors")

    # Tier 4: Enrichment (from Open Library)
    cover_url: Optional[str] = Field(None, description="Book cover image URL")
    subjects_lcsh: List[str] = Field(default_factory=list, description="Library of Congress Subject Headings")
    first_publish_year: Optional[int] = Field(None, description="Original publication year")

    # Extraction metadata
    extraction_source: Optional[str] = Field(None, description="How metadata was extracted")
    extraction_confidence: Optional[float] = Field(None, description="Confidence score 0-1")
    extracted_at: Optional[datetime] = Field(None, description="When extraction occurred")
    enriched_at: Optional[datetime] = Field(None, description="When Open Library enrichment occurred")


# JSON schema for structured LLM output
METADATA_EXTRACTION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "book_metadata",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Official book title"
                },
                "subtitle": {
                    "type": ["string", "null"],
                    "description": "Book subtitle if any"
                },
                "authors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Primary author names"
                },
                "isbn": {
                    "type": ["string", "null"],
                    "description": "ISBN-10 or ISBN-13 if found"
                },
                "lccn": {
                    "type": ["string", "null"],
                    "description": "Library of Congress Control Number if found"
                },
                "publisher": {
                    "type": ["string", "null"],
                    "description": "Publishing house name"
                },
                "publication_year": {
                    "type": ["integer", "null"],
                    "description": "Year of publication"
                },
                "language": {
                    "type": "string",
                    "description": "ISO 639-1 language code (e.g., 'en', 'es')"
                },
                "description": {
                    "type": ["string", "null"],
                    "description": "Brief book summary (1-3 sentences)"
                },
                "subjects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Subject keywords/topics"
                },
                "contributors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "role": {"type": "string"}
                        },
                        "required": ["name", "role"],
                        "additionalProperties": False
                    },
                    "description": "Other contributors (editor, translator, illustrator)"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score 0.0-1.0"
                }
            },
            "required": ["title", "authors", "language", "confidence"],
            "additionalProperties": False
        }
    }
}
