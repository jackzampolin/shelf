"""
Phase 2: Rich progress display for sequential bbox extraction.

Shows real-time feedback during slow vision model calls.
"""

import time
from typing import Optional
from rich.live import Live
from rich.console import Group
from rich.text import Text
from rich.table import Table
from rich.panel import Panel


class BboxExtractionProgress:
    """
    Live progress display for bbox extraction.

    Shows:
    - Current page being processed
    - Time waiting for response
    - TTFT (time to first token) when available
    - Token count as response streams
    - Final cost/time/tokens after completion
    """

    def __init__(self, total_pages: int):
        self.total_pages = total_pages
        self.current_page = 0
        self.live = None
        self.recent_results = []  # Last 5 completions

        self.call_start_time = None
        self.ttft = None
        self.tokens_received = 0

    def __enter__(self):
        self.live = Live(auto_refresh=True, refresh_per_second=4)
        self.live.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.live:
            self.live.stop()

    def start_page(self, page_num: int, description: str):
        """Start processing a page."""
        self.current_page = page_num
        self.call_start_time = time.time()
        self.ttft = None
        self.tokens_received = 0

        self._render(f"[yellow]⏳ {description}")

    def update_streaming(self, tokens_received: int, ttft: Optional[float] = None):
        """Update with streaming progress."""
        self.tokens_received = tokens_received
        if ttft and not self.ttft:
            self.ttft = ttft

        elapsed = time.time() - self.call_start_time if self.call_start_time else 0

        status_parts = [f"[yellow]⏳ Page {self.current_page}"]

        if self.ttft:
            status_parts.append(f"TTFT {self.ttft:.1f}s")

        if tokens_received > 0:
            status_parts.append(f"{tokens_received} tokens")

        status_parts.append(f"{elapsed:.1f}s")

        self._render(" | ".join(status_parts))

    def complete_page(self, page_num: int, result_summary: str):
        """Mark page complete with final summary."""
        elapsed = time.time() - self.call_start_time if self.call_start_time else 0

        # Add to recent results
        self.recent_results.append(f"[green]✓ Page {page_num}: {result_summary}")
        if len(self.recent_results) > 5:
            self.recent_results.pop(0)

        self._render(f"[green]✓ Page {page_num}: {result_summary}")

    def _render(self, current_status: str):
        """Render current state to Live display."""
        if not self.live:
            return

        # Progress summary
        summary = Text()
        summary.append(f"Phase 2: Extracting Bboxes ", style="bold blue")
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

    def render_summary(self, total_cost: float, total_time: float, pages_processed: int):
        """Render final summary panel."""
        if not self.live:
            return

        summary_text = f"""[green]✓ Phase 2 Complete[/green]

[cyan]Pages:[/cyan] {pages_processed}
[cyan]Cost:[/cyan] ${total_cost:.4f}
[cyan]Time:[/cyan] {total_time:.1f}s
"""

        panel = Panel(
            summary_text,
            title="[bold]Bbox Extraction Summary[/bold]",
            border_style="green"
        )

        self.live.update(panel)
