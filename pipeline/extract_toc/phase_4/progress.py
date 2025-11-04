"""
Phase 4: Rich progress display for bbox OCR.

Shows real-time feedback during Tesseract OCR processing.
"""

import time
from typing import Optional
from rich.live import Live
from rich.console import Group
from rich.text import Text
from rich.table import Table
from rich.panel import Panel


class BboxOCRProgress:
    """
    Live progress display for bbox OCR.

    Shows:
    - Current page being processed
    - Number of bboxes being OCR'd
    - Time per page
    - Average confidence
    """

    def __init__(self, total_pages: int):
        self.total_pages = total_pages
        self.current_page = 0
        self.live = None
        self.recent_results = []

        self.call_start_time = None

    def __enter__(self):
        self.live = Live(auto_refresh=True, refresh_per_second=4)
        self.live.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.live:
            self.live.stop()

    def start_page(self, page_num: int, description: str):
        """Start OCR on a page."""
        self.current_page = page_num
        self.call_start_time = time.time()

        self._render(f"[yellow]⏳ {description}")

    def complete_page(self, page_num: int, result_summary: str):
        """Mark page complete with final summary."""
        # Add to recent results
        self.recent_results.append(f"Page {page_num}: {result_summary}")
        if len(self.recent_results) > 5:
            self.recent_results.pop(0)

        self._render(f"[green]✓ Page {page_num}: {result_summary}")

    def _render(self, current_status: str):
        """Render current state to Live display."""
        if not self.live:
            return

        # Progress summary
        summary = Text()
        summary.append(f"Phase 4: OCR Bboxes ", style="bold blue")
        summary.append(f"({self.current_page}/{self.total_pages})", style="cyan")

        # Current operation
        current = Text.from_markup(current_status)

        # Recent results table
        recent_table = Table.grid(padding=(0, 1))
        for result in self.recent_results[-5:]:
            recent_table.add_row(Text.from_markup(result))

        # Combine
        if self.recent_results:
            group = Group(summary, current, "", recent_table)
        else:
            group = Group(summary, current)

        self.live.update(group)
