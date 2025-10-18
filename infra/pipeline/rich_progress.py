"""Rich-based progress bar implementations.

Drop-in replacements for the custom ProgressBar class using the Rich library.
Provides two variants:
- RichProgressBar: Simple progress bar
- RichProgressBarHierarchical: Progress bar with hierarchical sections
"""

from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)
from rich.live import Live
from rich.console import Console, Group
from rich.tree import Tree
import threading
from typing import Dict, List


class RichProgressBar:
    """Simple progress bar using Rich library.

    Drop-in replacement for ProgressBar that uses Rich internally.
    Handles sequential progress bars cleanly with transient mode.
    """

    def __init__(self, total: int, prefix: str = "", width: int = 40, unit: str = "items"):
        """Initialize progress bar.

        Args:
            total: Total number of items to process
            prefix: Text to show before the progress bar
            width: Width of the progress bar in characters
            unit: Unit name for rate display (default: "items")
        """
        self.total = total
        self.prefix = prefix
        self.unit = unit

        # Create custom columns to match current format
        self._progress = Progress(
            TextColumn(f"{prefix}{{task.description}}"),  # Prefix + description
            BarColumn(bar_width=width),
            TaskProgressColumn(),  # Shows "X/Y"
            TextColumn("•"),
            TextColumn("{task.fields[rate]}", justify="right"),
            TextColumn("•"),
            TimeRemainingColumn(),
            TextColumn("•"),
            TextColumn("{task.fields[suffix]}", justify="right"),
            transient=True,  # Disappears when context exits
        )

        self._task_id = None
        self._started = False

    def __enter__(self):
        self._progress.__enter__()
        self._task_id = self._progress.add_task(
            "",  # No description by default
            total=self.total,
            rate="",
            suffix=""
        )
        self._started = True
        return self

    def __exit__(self, *args):
        return self._progress.__exit__(*args)

    def update(self, current: int, suffix: str = ""):
        """Update progress bar.

        Args:
            current: Current number of items processed
            suffix: Optional suffix text to append
        """
        if not self._started:
            # Auto-start if used without context manager
            self.__enter__()

        # Calculate rate
        elapsed = self._progress.tasks[self._task_id].elapsed or 0.01
        rate = f"{current / elapsed:.1f} {self.unit}/sec" if elapsed > 0 else ""

        self._progress.update(
            self._task_id,
            completed=current,
            rate=rate,
            suffix=suffix
        )

    def finish(self, message: str = ""):
        """Finish progress and print message.

        Args:
            message: Optional completion message to display
        """
        if self._started:
            self.__exit__(None, None, None)
            self._started = False

        # Print completion message (progress bar is now cleared due to transient=True)
        if message:
            print(message)


class RichProgressBarHierarchical:
    """Progress bar with hierarchical sections support using Rich library.

    Supports:
    - Main progress bar
    - Hierarchical sections (e.g., "Running (3)", "Recent (5)")
    - Dynamic sub-items within sections
    - Thread-safe updates
    - Transient mode for clean sequential display
    """

    def __init__(self, total: int, prefix: str = "", width: int = 40, unit: str = "items"):
        """Initialize hierarchical progress bar.

        Args:
            total: Total number of items to process
            prefix: Text to show before the progress bar
            width: Width of the progress bar in characters
            unit: Unit name for rate display (default: "items")
        """
        self.total = total
        self.prefix = prefix
        self.unit = unit

        # Main progress bar
        self._progress = Progress(
            TextColumn(f"{prefix}{{task.description}}"),
            BarColumn(bar_width=width),
            TaskProgressColumn(),
            TextColumn("{task.fields[suffix]}", justify="right"),
            transient=True
        )

        self._task_id = None
        self._live = None
        self._console = Console()

        # Hierarchical state
        self._sections: Dict[str, dict] = {}  # section_id -> {"title": str, "items": List[str]}
        self._sub_lines: Dict[str, str] = {}  # line_id -> message
        self._section_order: List[str] = []  # Track section order
        self._lock = threading.Lock()  # Thread safety for section updates

        self._started = False

    def __enter__(self):
        self._task_id = self._progress.add_task("", total=self.total, suffix="")
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=4,
            transient=True
        )
        self._live.__enter__()
        self._started = True
        return self

    def __exit__(self, *args):
        if self._live:
            self._live.__exit__(*args)
        self._started = False

    def _render(self):
        """Render progress bar + hierarchical sections."""
        with self._lock:
            components = [self._progress]

            # Add hierarchical sections if present
            if self._sections and self._section_order:
                tree = Tree("")

                for section_id in self._section_order:
                    if section_id not in self._sections:
                        continue

                    section_data = self._sections[section_id]
                    title = section_data["title"]
                    items = section_data["items"]

                    section_node = tree.add(f"[bold]{title}[/bold]")

                    # Add items that have messages
                    valid_items = [item_id for item_id in items if item_id in self._sub_lines]

                    if not valid_items:
                        section_node.add("[dim](none)[/dim]")
                    else:
                        for item_id in valid_items:
                            msg = self._sub_lines[item_id]
                            section_node.add(msg)

                components.append(tree)

            return Group(*components)

    def update(self, current: int, suffix: str = ""):
        """Update progress bar.

        Args:
            current: Current number of items processed
            suffix: Optional suffix text to append
        """
        if not self._started:
            self.__enter__()

        self._progress.update(self._task_id, completed=current, suffix=suffix)

        # Refresh live display with updated sections
        if self._live:
            self._live.update(self._render())

    def add_sub_line(self, line_id: str, message: str):
        """Add or update a sub-status line.

        Args:
            line_id: Unique identifier for this status line
            message: Status message to display
        """
        with self._lock:
            self._sub_lines[line_id] = message

        # Trigger re-render
        if self._live:
            self._live.update(self._render())

    def remove_sub_line(self, line_id: str):
        """Remove a sub-status line.

        Args:
            line_id: Unique identifier of the line to remove
        """
        with self._lock:
            if line_id in self._sub_lines:
                del self._sub_lines[line_id]

        if self._live:
            self._live.update(self._render())

    def set_section(self, section_id: str, title: str, line_ids: List[str]):
        """Create or update a hierarchical section.

        Args:
            section_id: Unique identifier for this section
            title: Section header (e.g., "Running (3):")
            line_ids: List of line_ids to include in this section
        """
        with self._lock:
            self._sections[section_id] = {
                "title": title,
                "items": line_ids
            }

            # Track section order (add if new)
            if section_id not in self._section_order:
                self._section_order.append(section_id)

        # Trigger re-render
        if self._live:
            self._live.update(self._render())

    def clear_sections(self):
        """Remove all sections and return to flat display."""
        with self._lock:
            self._sections.clear()
            self._section_order.clear()

        if self._live:
            self._live.update(self._render())

    def set_status(self, message: str):
        """Display a temporary status message without updating progress.

        Useful for showing transient states like "Rate limited, waiting..."

        Args:
            message: Status message to display
        """
        # Update task description temporarily
        self._progress.update(self._task_id, description=message)

        if self._live:
            self._live.update(self._render())

    def finish(self, message: str = ""):
        """Clear progress bar and print completion message.

        Args:
            message: Optional completion message to display
        """
        if self._started:
            self.__exit__(None, None, None)

        if message:
            print(message)
