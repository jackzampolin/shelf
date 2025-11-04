"""
Phase 2: Bounding Box Extraction

Vision model places bounding boxes around ToC structural elements.
"""

from .extractor import extract_bboxes

__all__ = ["extract_bboxes"]
