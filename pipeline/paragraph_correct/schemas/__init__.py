"""
Paragraph-Correct Stage Schemas

One schema per file for clarity and maintainability:
- page_output.py: What we write to disk
- page_metrics.py: What we track in checkpoint
- page_report.py: Quality metrics for CSV report

Note: LLM response schemas are in vision/schemas/llm_response.py
(they're tightly coupled to the vision LLM call)
"""

from .page_output import ParagraphCorrectPageOutput
from .page_metrics import ParagraphCorrectPageMetrics
from .page_report import ParagraphCorrectPageReport

__all__ = [
    "ParagraphCorrectPageOutput",
    "ParagraphCorrectPageMetrics",
    "ParagraphCorrectPageReport",
]
