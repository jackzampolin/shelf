"""
Metadata extraction phase for ocr-pages stage.

Extracts book metadata using web-search LLM after OCR/blend completes.
"""

from .processor import process_metadata, create_metadata_tracker

__all__ = ["process_metadata", "create_metadata_tracker"]
