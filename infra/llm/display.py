"""
Unified display formatting for all LLM operations.

Standard format:
  Progress: ⏳ {phase-name} [progress bar] {N}/{M} • {stats}
  Complete: ✅ {phase-name}: {N}/{M}                ({time}) {tokens} {cost}¢

All LLM operations (single, batch, agent, OCR) should use these functions
for consistent terminal output.
"""

from dataclasses import dataclass
from typing import Optional
from rich.text import Text
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn, SpinnerColumn

from .display_format import format_token_string, format_token_count


# Standard widths for consistent alignment
PHASE_NAME_WIDTH = 45
DESCRIPTION_WIDTH = 45


@dataclass
class DisplayStats:
    """Statistics for display formatting."""
    completed: int = 0
    total: int = 0
    time_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    # Optional extras for specific use cases
    chars: Optional[int] = None  # For OCR
    avg_time_per_item: Optional[float] = None  # For OCR


def format_phase_complete(
    phase_name: str,
    stats: DisplayStats,
) -> Text:
    """
    Format a phase completion line.

    Output: ✅ {phase-name}: {N}/{M}                ({time}) {tokens} {cost}¢
    """
    text = Text()
    text.append("✅ ", style="green")

    description = f"{phase_name}: {stats.completed}/{stats.total}"
    text.append(f"{description:<{DESCRIPTION_WIDTH}}", style="")

    text.append(f"({stats.time_seconds:6.1f}s)", style="dim")

    token_str = format_token_string(
        stats.prompt_tokens,
        stats.completion_tokens,
        stats.reasoning_tokens,
        fixed_width=True
    )
    text.append(f" {token_str}", style="cyan")

    cost_cents = stats.cost_usd * 100
    text.append(f" {cost_cents:6.2f}¢", style="yellow")

    return text


def format_phase_error(
    phase_name: str,
    error_message: str,
    stats: Optional[DisplayStats] = None,
) -> Text:
    """
    Format a phase error line.

    Output: ❌ {phase-name}: {error}
    """
    text = Text()
    text.append("❌ ", style="red")

    if stats:
        description = f"{phase_name}: {stats.completed}/{stats.total} - {error_message}"
    else:
        description = f"{phase_name}: {error_message}"
    text.append(description, style="")

    return text


def format_ocr_complete(
    phase_name: str,
    stats: DisplayStats,
) -> Text:
    """
    Format an OCR phase completion line with char count.

    Output: ✅ {phase-name}: {N}/{M}                ({time}) ({chars})chars {avg}s/pg {cost}¢
    """
    text = Text()
    text.append("✅ ", style="green")

    description = f"{phase_name}: {stats.completed}/{stats.total}"
    text.append(f"{description:<{DESCRIPTION_WIDTH}}", style="")

    text.append(f"({stats.time_seconds:6.1f}s)", style="dim")

    if stats.chars is not None:
        char_str = f"({format_token_count(stats.chars, width=6)})chars"
        text.append(f" {char_str}", style="cyan")

    if stats.avg_time_per_item is not None:
        text.append(f" {stats.avg_time_per_item:5.2f}s/pg", style="dim")

    cost_cents = stats.cost_usd * 100
    text.append(f" {cost_cents:6.2f}¢", style="yellow")

    return text


def print_phase_complete(phase_name: str, stats: DisplayStats):
    """Print a phase completion line to console."""
    Console().print(format_phase_complete(phase_name, stats))


def print_phase_error(phase_name: str, error_message: str, stats: Optional[DisplayStats] = None):
    """Print a phase error line to console."""
    Console().print(format_phase_error(phase_name, error_message, stats))


def print_ocr_complete(phase_name: str, stats: DisplayStats):
    """Print an OCR phase completion line to console."""
    Console().print(format_ocr_complete(phase_name, stats))


def format_stage_complete(stage_name: str, stats: DisplayStats) -> Text:
    """
    Format a stage completion line (sums all phases).

    Output: ✅ Stage complete: {stage-name}          ({time}) {tokens} {cost}¢
    """
    text = Text()
    text.append("✅ ", style="green")

    description = f"Stage complete: {stage_name}"
    text.append(f"{description:<{DESCRIPTION_WIDTH}}", style="bold")

    text.append(f"({stats.time_seconds:6.1f}s)", style="dim")

    token_str = format_token_string(
        stats.prompt_tokens,
        stats.completion_tokens,
        stats.reasoning_tokens,
        fixed_width=True
    )
    text.append(f" {token_str}", style="cyan")

    cost_cents = stats.cost_usd * 100
    text.append(f" {cost_cents:6.2f}¢", style="yellow")

    return text


def print_stage_complete(stage_name: str, stats: DisplayStats):
    """Print a stage completion line to console."""
    Console().print(format_stage_complete(stage_name, stats))


def create_phase_progress(phase_name: str, total: int) -> tuple[Progress, int]:
    """
    Create a progress bar for a phase.

    Returns: (Progress instance, task_id)

    Display format: ⏳ {phase-name} [████████░░░░] 45% {N}/{M} • {suffix}
    """
    progress = Progress(
        TextColumn(f"⏳ {phase_name}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        TextColumn("{task.fields[suffix]}", justify="right"),
        transient=True
    )
    progress.start()
    task_id = progress.add_task("", total=total, suffix="starting...")
    return progress, task_id


def update_phase_progress(
    progress: Progress,
    task_id: int,
    completed: int,
    total: int,
    cost_usd: float = 0.0,
    extra: str = ""
):
    """
    Update a phase progress bar.

    Suffix format: {N}/{M} • ${cost} {extra}
    """
    parts = [f"{completed}/{total}"]
    if cost_usd > 0:
        parts.append(f"${cost_usd:.4f}")
    if extra:
        parts.append(extra)

    suffix = " • ".join(parts)
    progress.update(task_id, completed=completed, suffix=suffix)


def stop_phase_progress(progress: Progress):
    """Stop and clean up a progress bar."""
    progress.stop()


# Convenience class for managing progress lifecycle
class PhaseProgress:
    """
    Context manager for phase progress display.

    Usage:
        with PhaseProgress("evaluation", total=74) as pp:
            for item in items:
                process(item)
                pp.update(completed=i, cost_usd=total_cost)
    """

    def __init__(self, phase_name: str, total: int):
        self.phase_name = phase_name
        self.total = total
        self.progress = None
        self.task_id = None

    def __enter__(self):
        self.progress, self.task_id = create_phase_progress(self.phase_name, self.total)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.progress:
            stop_phase_progress(self.progress)
        return False

    def update(self, completed: int, cost_usd: float = 0.0, extra: str = ""):
        if self.progress and self.task_id is not None:
            update_phase_progress(
                self.progress,
                self.task_id,
                completed,
                self.total,
                cost_usd,
                extra
            )


class SingleCallSpinner:
    """
    Context manager for showing a spinner during single LLM calls.

    Usage:
        with SingleCallSpinner("pattern") as spinner:
            result = llm_client.call(...)
        # Spinner stops, then print completion line
    """

    def __init__(self, call_name: str):
        self.call_name = call_name
        self.progress = None
        self.task_id = None

    def __enter__(self):
        self.progress = Progress(
            TextColumn(f"⏳ {self.call_name}: waiting for response..."),
            transient=True
        )
        self.progress.start()
        self.task_id = self.progress.add_task("")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.progress:
            self.progress.stop()
        return False
