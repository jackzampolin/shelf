#!/usr/bin/env python3
"""
Parallelization configuration for all pipeline stages.

Centralized configuration for worker counts, rate limits, and chunk sizes
across the entire processing pipeline.
"""

PARALLELIZATION_CONFIG = {
    "ocr": {
        "max_workers": 8,
        "description": "OCR extraction"
    },
    "correction": {
        "max_workers": 30,
        "rate_limit": 150,  # calls per minute
        "description": "LLM correction"
    },
    "fix": {
        "max_workers": 15,
        "description": "Agent 4 fixes"
    },
    "structure": {
        "page_numbers": {
            "max_workers": 30,
            "description": "Page number extraction"
        },
        "footnotes": {
            "max_workers": 10,
            "chunk_size": 10,  # pages per chunk
            "description": "Footnote extraction"
        },
        "bibliography": {
            "max_workers": 10,
            "chunk_size": 5,  # pages per chunk (bibliographies are denser)
            "description": "Bibliography parsing"
        },
        "output_generation": {
            "max_workers": 10,
            "description": "Chapter file generation"
        }
    },
    "quality": {
        "max_workers": 5,
        "sample_size": 5,  # number of chapters to sample
        "description": "Quality review sampling"
    }
}


def get_config(stage: str, phase: str = None) -> dict:
    """
    Get configuration for a specific stage or phase.

    Args:
        stage: Pipeline stage (ocr, correction, fix, structure, quality)
        phase: Optional phase within stage (for structure stage)

    Returns:
        Dictionary with configuration parameters

    Examples:
        >>> get_config("correction")
        {'max_workers': 30, 'rate_limit': 150, 'description': 'LLM correction'}

        >>> get_config("structure", "footnotes")
        {'max_workers': 10, 'chunk_size': 10, 'description': 'Footnote extraction'}
    """
    if phase:
        return PARALLELIZATION_CONFIG.get(stage, {}).get(phase, {})
    return PARALLELIZATION_CONFIG.get(stage, {})
