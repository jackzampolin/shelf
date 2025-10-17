"""Terminal progress bar with in-place updates."""

import time


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

    def update(self, current: int, suffix: str = ""):
        """Update progress bar in place.

        Args:
            current: Current number of items processed
            suffix: Optional suffix text to append (e.g., "3 failed")
        """
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
        """Print final newline and completion message.

        Args:
            message: Optional completion message to display
        """
        print()  # New line after progress bar
        if message:
            print(message)

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

    def _render_all(self, main_line: str):
        """Render main progress bar and all sub-status lines.

        Args:
            main_line: The formatted main progress bar line
        """
        # Clear previous output if we had multiple lines
        if self._total_lines > 1:
            # Move cursor up to start of our output block
            print(f"\033[{self._total_lines}A", end='', flush=True)

        # Print main line (with carriage return to overwrite)
        print(f"\r{main_line}\033[K", end='', flush=True)  # Clear to end of line

        if self._sub_lines:
            # Print newline after main bar if we have sub-lines
            print()

            # Print sub-lines (sorted by ID for stable order)
            for line_id in sorted(self._sub_lines.keys()):
                print(f"  {self._sub_lines[line_id]}\033[K", flush=True)  # Clear to end of line

        # Track how many lines we printed (for next clear)
        self._total_lines = 1 + len(self._sub_lines)
