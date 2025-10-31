"""
Tools for Paragraph Correction

Business logic for the paragraph-correct stage:
- processor.py: Main correction logic with LLMBatchProcessor
- quality_metrics.py: Similarity calculations
- report_generator.py: CSV report generation
"""

from .processor import correct_pages
from .quality_metrics import calculate_similarity_metrics
from .report_generator import generate_report

__all__ = [
    "correct_pages",
    "calculate_similarity_metrics",
    "generate_report",
]
