from rich.text import Text
from rich.console import Console

from infra.llm.display_format import format_token_string


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
    metrics_manager,
    metric_prefix: str = ""
):
    cumulative = metrics_manager.get_cumulative_metrics(prefix=metric_prefix)
    display_completed = cumulative.get('total_requests', batch_stats.completed)
    display_total = total_items
    display_prompt_tokens = cumulative.get('total_prompt_tokens', batch_stats.total_prompt_tokens)
    display_completion_tokens = cumulative.get('total_completion_tokens', batch_stats.total_tokens)
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
