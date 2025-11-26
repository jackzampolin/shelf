from rich.text import Text
from rich.console import Console

from infra.llm.display_format import format_token_string, format_token_count


def format_ocr_summary(
    batch_name: str,
    completed: int,
    total: int,
    time_seconds: float,
    total_chars: int,
    cost_usd: float,
    description_width: int = 40
) -> Text:
    """Format OCR batch summary with char count and timing."""
    text = Text()
    text.append("✅ ", style="green")

    description = f"{batch_name}: {completed}/{total} pages"
    text.append(f"{description:<{description_width}}", style="")

    text.append(f"({time_seconds:5.1f}s)", style="dim")

    # Char count using same K/M formatting as tokens
    char_str = f"({format_token_count(total_chars)})chars"
    text.append(f" {char_str}", style="cyan")

    # Avg time per page
    avg_time = time_seconds / completed if completed > 0 else 0
    text.append(f" {avg_time:.2f}s/pg", style="dim")

    cost_cents = cost_usd * 100
    text.append(f" {cost_cents:5.2f}¢", style="yellow")

    return text


def format_batch_summary(
    batch_name: str,
    completed: int,
    total: int,
    time_seconds: float,
    prompt_tokens: int,
    completion_tokens: int,
    reasoning_tokens: int,
    cost_usd: float,
    unit: str = "requests",
    description_width: int = 45
) -> Text:
    text = Text()
    text.append("✅ ", style="green")

    description = f"{batch_name}: {completed}/{total} {unit}"
    text.append(f"{description:<{description_width}}", style="")

    text.append(f" ({time_seconds:4.1f}s)", style="dim")

    token_str = format_token_string(prompt_tokens, completion_tokens, reasoning_tokens)
    text.append(f" {token_str:>22}", style="cyan")

    cost_cents = cost_usd * 100
    text.append(f" {cost_cents:5.2f}¢", style="yellow")

    return text


def display_summary(
    batch_name: str,
    batch_stats,
    elapsed: float,
    total_items: int,
    completed_items: int,
    metrics_manager,
    metric_prefix: str = ""
):
    """Display summary of batch processing.

    Args:
        batch_name: Name of the batch operation
        batch_stats: BatchStats from this run
        elapsed: Elapsed time for this run
        total_items: Total items in phase (from tracker status)
        completed_items: Completed items in phase (from tracker status)
        metrics_manager: MetricsManager for cost/token data
        metric_prefix: Prefix for filtering metrics
    """
    cumulative = metrics_manager.get_cumulative_metrics(prefix=metric_prefix)

    # Use tracker-provided counts (source of truth for completion)
    display_completed = completed_items
    display_total = total_items

    # Use cumulative metrics for cost/tokens (accurate across runs)
    display_prompt_tokens = cumulative.get('total_prompt_tokens', batch_stats.total_prompt_tokens)
    display_completion_tokens = cumulative.get('total_completion_tokens', batch_stats.total_completion_tokens)
    display_reasoning_tokens = cumulative.get('total_reasoning_tokens', batch_stats.total_reasoning_tokens)
    display_cost = cumulative.get('total_cost_usd', batch_stats.total_cost_usd)

    runtime_metrics = metrics_manager.get("stage_runtime")
    display_time = runtime_metrics.get("time_seconds", elapsed) if runtime_metrics else elapsed

    summary_text = format_batch_summary(
        batch_name=batch_name,
        completed=display_completed,
        total=display_total,
        time_seconds=display_time,
        prompt_tokens=display_prompt_tokens,
        completion_tokens=display_completion_tokens,
        reasoning_tokens=display_reasoning_tokens,
        cost_usd=display_cost,
        unit="requests"
    )

    console = Console()
    console.print(summary_text)
