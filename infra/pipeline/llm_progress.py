"""Simple progress display for LLM calls in pipeline stages."""

from rich.console import Console
from rich.live import Live
from rich.text import Text

from infra.llm.display_format import format_individual_call


class LLMCallProgress:
    """
    Simple progress display for LLM calls.

    Shows one line per call:
    - While waiting: "  🔧 description..."
    - After complete: "  🔧 description (time) tokens cost"
    """

    def __init__(self, console: Console = None):
        self.console = console or Console()
        self.lines = []
        self.live = None

    def _render(self):
        """Render all lines."""
        if not self.lines:
            return Text("")

        result = Text()
        for i, line_text in enumerate(self.lines):
            if i > 0:
                result.append("\n")
            result.append(line_text)
        return result

    def start_call(self, description: str):
        """Start a new LLM call."""
        line = Text()
        line.append("  🔧 ", style="dim")
        line.append(f"{description}...", style="")
        self.lines.append(line)

        if self.live:
            self.live.update(self._render())

    def complete_call(self, time_seconds: float, prompt_tokens: int, completion_tokens: int,
                     reasoning_tokens: int, cost_usd: float):
        """Complete the most recent LLM call with metrics."""
        if not self.lines:
            return

        # Replace the last line with completed version
        last_line = self.lines[-1]

        # Extract just the description (remove "..." and "🔧 ")
        description = last_line.plain.replace("  🔧 ", "").replace("...", "").strip()

        # Use standard formatter
        new_line = format_individual_call(
            description=description,
            time_seconds=time_seconds,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            cost_usd=cost_usd,
            icon="🔧",
            description_width=45
        )

        self.lines[-1] = new_line

        if self.live:
            self.live.update(self._render())

    def __enter__(self):
        """Start live display."""
        self.live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=4,
            transient=False
        )
        self.live.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop live display."""
        if self.live:
            self.live.__exit__(exc_type, exc_val, exc_tb)
