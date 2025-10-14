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
    """In-place terminal progress bar with \\r updates.

    Displays a visual progress bar that updates in place using carriage return,
    showing percentage, count, processing rate, and estimated time remaining.

    Example:
        >>> progress = ProgressBar(total=100, prefix="Processing: ")
        >>> for i in range(100):
        ...     progress.update(i + 1, suffix="ok")
        >>> progress.finish("Complete!")

        Output (updates in place):
        Processing: [████████████████████░░░░] 80% (80/100) - 10.5 items/sec - ETA 2s - ok
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

    def update(self, current: int, suffix: str = ""):
        """Update progress bar in place.

        Args:
            current: Current number of items processed
            suffix: Optional suffix text to append (e.g., "3 failed")
        """
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
        output = f"\r{self.prefix}[{bar}] {percent:.0f}% ({current}/{self.total})"

        if rate > 0:
            output += f" - {rate:.1f} {self.unit}/sec"

        if eta > 0 and eta < 3600:  # Only show ETA if < 1 hour
            output += f" - ETA {format_seconds(eta)}"

        if suffix:
            output += f" - {suffix}"

        # Print with \r (carriage return) to overwrite
        print(output, end='', flush=True)
        self.last_update = current

    def finish(self, message: str = ""):
        """Print final newline and completion message.

        Args:
            message: Optional completion message to display
        """
        print()  # New line after progress bar
        if message:
            print(message)
