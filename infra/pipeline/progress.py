"""Terminal progress bar with in-place updates."""

import time
import threading
from dataclasses import dataclass
from typing import List, Dict


def format_seconds(seconds: float) -> str:
    """Format seconds into human-readable time string.

    Args:
        seconds: Time in seconds

    Returns:
        Formatted string like "2m 15s" or "45s"
    """
    if seconds < 60:
        return f"{int(seconds)}s"

    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"


@dataclass
class Section:
    """A hierarchical section of sub-items."""
    title: str              # "Running (3):"
    items: List[str]        # List of line_ids in this section


class ProgressBar:
    """In-place terminal progress bar with \\r updates and optional sub-status lines.

    Displays a visual progress bar that updates in place using carriage return,
    showing percentage, count, processing rate, and estimated time remaining.
    Supports multiple sub-status lines below the main progress bar.

    Example:
        >>> progress = ProgressBar(total=100, prefix="Processing: ")
        >>> for i in range(100):
        ...     progress.update(i + 1, suffix="ok")
        >>> progress.finish("Complete!")

        Output (updates in place):
        Processing: [████████████████████░░░░] 80% (80/100) - 10.5 items/sec - ETA 2s - ok
          p0001: Executing... (3.2s)
          p0002: Executing... (1.8s)
    """

    def __init__(
        self,
        total: int,
        prefix: str = "",
        width: int = 40,
        unit: str = "items"
    ):
        """Initialize progress bar.

        Args:
            total: Total number of items to process
            prefix: Text to show before the progress bar
            width: Width of the progress bar in characters (default: 40)
            unit: Unit name for rate display (default: "items")
        """
        self.total = total
        self.prefix = prefix
        self.width = width
        self.unit = unit
        self.start_time = time.time()
        self.last_update = 0
        self._sub_lines = {}  # {line_id: message} for sub-status lines
        self._total_lines = 0  # Track total lines printed
        self._last_current = 0  # Last progress value
        self._last_suffix = ""  # Last suffix value

        # Section support for hierarchical display
        self._sections: Dict[str, Section] = {}  # section_id → Section
        self._section_order: List[str] = []  # Ordered section IDs

        # Thread safety for concurrent updates
        self._lock = threading.Lock()

    def update(self, current: int, suffix: str = ""):
        """Update progress bar in place.

        Args:
            current: Current number of items processed
            suffix: Optional suffix text to append (e.g., "3 failed")
        """
        with self._lock:
            self._last_current = current
            self._last_suffix = suffix

            # Calculate metrics
            percent = (current / self.total) * 100 if self.total > 0 else 0
            filled = int(self.width * current // self.total) if self.total > 0 else 0
            bar = '█' * filled + '░' * (self.width - filled)

            # Calculate rate and ETA
            elapsed = time.time() - self.start_time
            rate = current / elapsed if elapsed > 0 else 0
            remaining = self.total - current
            eta = remaining / rate if rate > 0 else 0

            # Format output
            output = f"{self.prefix}[{bar}] {percent:.0f}% ({current}/{self.total})"

            if rate > 0:
                output += f" - {rate:.1f} {self.unit}/sec"

            if eta > 0 and eta < 3600:  # Only show ETA if < 1 hour
                output += f" - ETA {format_seconds(eta)}"

            if suffix:
                output += f" - {suffix}"

            self._render_all(output)
            self.last_update = current

    def finish(self, message: str = ""):
        """Clear progress bar and print completion message.

        Clears the progress bar in place (without moving cursor up) and prints
        a completion message. This prevents accidentally clearing lines that were
        printed BEFORE the progress bar started.

        Args:
            message: Optional completion message to display
        """
        with self._lock:
            # Key insight: The progress bar cursor is ALREADY at the end of the last line
            # After rendering N lines, cursor is at end of line N
            # We need to move up N-1 lines to get to line 1, clear all N lines,
            # then leave cursor at the beginning of line 1

            if self._total_lines > 0:
                # Move cursor to start of first progress bar line
                # (cursor is currently at end of last line)
                if self._total_lines > 1:
                    print(f"\r\033[{self._total_lines - 1}A", end='', flush=True)
                else:
                    print("\r", end='', flush=True)  # Just return to start of single line

                # Clear all progress bar lines
                for i in range(self._total_lines):
                    print("\033[K", end='', flush=True)  # Clear current line
                    if i < self._total_lines - 1:
                        print("\n", end='', flush=True)  # Move down to next line

                # Cursor is now at start of line after last cleared line
                # Move back up to where first line was
                if self._total_lines > 1:
                    print(f"\033[{self._total_lines - 1}A", end='', flush=True)

            # Clear internal state
            self._sub_lines.clear()
            self._sections.clear()
            self._section_order.clear()
            self._total_lines = 0

            # Print completion message on clean line (or just newline)
            if message:
                print(message, flush=True)
            else:
                print(flush=True)  # Move cursor past cleared area

    def set_status(self, message: str):
        """Display a temporary status message without updating progress.

        Useful for showing transient states like "Rate limited, waiting..."
        without affecting the progress bar state.

        Args:
            message: Status message to display
        """
        # When sub-lines exist, re-render everything with this status
        # Otherwise just print the status
        if self._sub_lines:
            self._render_all(f"{self.prefix}{message}")
        else:
            print(f"\r{self.prefix}{message}", end='', flush=True)

    def add_sub_line(self, line_id: str, message: str):
        """Add or update a sub-status line below the main progress bar.

        Args:
            line_id: Unique identifier for this status line
            message: Status message to display
        """
        self._sub_lines[line_id] = message
        # Re-render with current progress
        if self._last_current > 0 or self._sub_lines:
            self.update(self._last_current, self._last_suffix)

    def remove_sub_line(self, line_id: str):
        """Remove a sub-status line.

        Args:
            line_id: Unique identifier of the line to remove
        """
        if line_id in self._sub_lines:
            del self._sub_lines[line_id]
            # Re-render with current progress
            self.update(self._last_current, self._last_suffix)

    def set_section(self, section_id: str, title: str, line_ids: List[str]):
        """Create or update a hierarchical section.

        Args:
            section_id: Unique identifier for this section
            title: Section header (e.g., "Running (3):")
            line_ids: List of line_ids to include in this section
        """
        # Create or update section
        self._sections[section_id] = Section(title=title, items=line_ids)

        # Track section order (add if new)
        if section_id not in self._section_order:
            self._section_order.append(section_id)

        # Don't re-render here - let update() handle it

    def clear_sections(self):
        """Remove all sections and return to flat display."""
        self._sections.clear()
        self._section_order.clear()
        # Re-render with current progress
        self.update(self._last_current, self._last_suffix)

    def _render_all(self, main_line: str):
        """Render main progress bar and all sub-status lines.

        Strategy: Build complete output as a list of lines, then print all at once.
        This is simpler and more robust than trying to track cursor positions.

        Args:
            main_line: The formatted main progress bar line
        """
        # Build complete output
        lines = [main_line]

        # Add hierarchical sections if present
        if self._sections:
            for i, section_id in enumerate(self._section_order):
                section = self._sections[section_id]
                is_last_section = (i == len(self._section_order) - 1)

                # Section header
                branch = "└─" if is_last_section else "├─"
                lines.append(f"   {branch} {section.title}")

                # Section items - filter to only valid items with messages
                valid_items = [lid for lid in section.items if lid in self._sub_lines]

                if not valid_items:
                    # Empty section
                    prefix = "      " if is_last_section else "   │  "
                    lines.append(f"{prefix}(none)")
                else:
                    for j, line_id in enumerate(valid_items):
                        is_last_item = (j == len(valid_items) - 1)
                        prefix = "      " if is_last_section else "   │  "
                        item_branch = "└─" if is_last_item else "├─"
                        message = self._sub_lines[line_id]
                        lines.append(f"{prefix}{item_branch} {message}")

        # Add flat sub-lines (backward compatible)
        elif self._sub_lines:
            for line_id in sorted(self._sub_lines.keys()):
                lines.append(f"  {self._sub_lines[line_id]}")

        # Strategy: On first render, use newlines to create lines.
        # On subsequent renders, move cursor up and overwrite in place.

        if self._total_lines > 0:
            # Subsequent render: move cursor back to first line and overwrite
            print(f"\033[{self._total_lines - 1}A", end='', flush=True)

            # Overwrite existing lines
            for i, line in enumerate(lines):
                print(f"\r{line}\033[K", end='', flush=True)
                if i < len(lines) - 1:
                    # Move down to next line (which already exists from previous render)
                    print("\033[1B", end='', flush=True)

            # Clear any extra lines from previous render
            if len(lines) < self._total_lines:
                extra_lines = self._total_lines - len(lines)
                for _ in range(extra_lines):
                    print("\033[1B\r\033[K", end='', flush=True)
                # Move back up to last actual line
                print(f"\033[{extra_lines}A", end='', flush=True)
        else:
            # First render: create new lines with newlines
            for i, line in enumerate(lines):
                print(f"\r{line}\033[K", end='', flush=True)
                if i < len(lines) - 1:
                    # Create new line below
                    print("\n", end='', flush=True)

        # Track total lines for next render
        self._total_lines = len(lines)
