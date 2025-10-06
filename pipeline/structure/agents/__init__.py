"""
Structure Stage Agents - Phase 1 Sliding Window Extraction

Three agents work together to extract clean text from page batches:
- extract_agent: Removes headers/footers, preserves body text
- verify_agent: Validates extraction quality
- reconcile_agent: Handles overlapping regions between batches
"""

from .extract_agent import extract_batch, extract_batch_safe
from .verify_agent import verify_extraction, verify_extraction_simple
from .reconcile_agent import (
    reconcile_overlaps,
    reconcile_overlaps_with_llm,
    merge_batch_results,
    text_similarity
)

__all__ = [
    'extract_batch',
    'extract_batch_safe',
    'verify_extraction',
    'verify_extraction_simple',
    'reconcile_overlaps',
    'reconcile_overlaps_with_llm',
    'merge_batch_results',
    'text_similarity'
]
