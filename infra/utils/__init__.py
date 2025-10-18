"""
Shared utilities for the pipeline.

Provides:
- PDF utilities: Page extraction, image handling, base64 encoding
"""

from infra.utils.pdf import (
    downsample_for_vision,
    get_page_from_book,
    get_pages_from_book,
    extract_page_images,
    image_to_base64,
    extract_page_image_base64
)

__all__ = [
    "downsample_for_vision",
    "get_page_from_book",
    "get_pages_from_book",
    "extract_page_images",
    "image_to_base64",
    "extract_page_image_base64",
]
