#!/usr/bin/env python3
from typing import Dict, List, Tuple, Optional

from ..schemas import RequestPhase


def calculate_rollups(metrics_manager, active_requests: Dict, sub_lines: Dict) -> Dict:
    """Calculate rollup metrics from metrics.json."""
    executing = {req_id: status for req_id, status in active_requests.items()
                if status.phase == RequestPhase.EXECUTING}

    waiting_count = sum(1 for req_id in executing.keys()
                       if "Waiting for response" in sub_lines.get(req_id, "") or not sub_lines.get(req_id))
    streaming_count = len(executing) - waiting_count

    ttfts = []
    streaming_times = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_reasoning_tokens = 0
    token_count = 0

    if metrics_manager:
        all_metrics = metrics_manager.get_all()

        for key, metrics in all_metrics.items():
            if metrics.get('ttft_seconds') is not None:
                ttfts.append(metrics['ttft_seconds'])

            if metrics.get('execution_time_seconds') is not None and metrics.get('ttft_seconds') is not None:
                streaming_time = metrics['execution_time_seconds'] - metrics['ttft_seconds']
                if streaming_time > 0:
                    streaming_times.append(streaming_time)

            if metrics.get('prompt_tokens') is not None:
                total_input_tokens += metrics.get('prompt_tokens', 0)
                total_output_tokens += metrics.get('completion_tokens', 0)
                total_reasoning_tokens += metrics.get('reasoning_tokens', 0)
                token_count += 1

    return {
        'ttfts': ttfts,
        'streaming_times': streaming_times,
        'total_input_tokens': total_input_tokens,
        'total_output_tokens': total_output_tokens,
        'total_reasoning_tokens': total_reasoning_tokens,
        'token_count': token_count,
        'active_count': len(executing),
        'waiting_count': waiting_count,
        'streaming_count': streaming_count,
    }


def percentile(values: List[float], p: float) -> Optional[float]:
    """Calculate percentile of values."""
    if not values:
        return None
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])


def format_rollup_lines(batch_stats, rollup_metrics: Dict) -> List[Tuple[str, str]]:
    """Format rollup metric display lines."""
    lines = []

    if batch_stats.requests_per_second > 0:
        lines.append((
            "rollup_throughput",
            f"[cyan]Throughput:[/cyan] [bold]{batch_stats.requests_per_second:.1f}[/bold] [dim]pages/sec[/dim]"
        ))

    if batch_stats.completed > 0:
        avg_cost_cents = (batch_stats.total_cost_usd / batch_stats.completed) * 100
        lines.append((
            "rollup_avg_cost",
            f"[cyan]Avg cost:[/cyan] [bold yellow]{avg_cost_cents:.2f}¢[/bold yellow][dim]/page[/dim]"
        ))

    active_count = rollup_metrics['active_count']
    waiting_count = rollup_metrics['waiting_count']
    streaming_count = rollup_metrics['streaming_count']

    if active_count > 0:
        parts = []
        if waiting_count > 0:
            parts.append(f"{waiting_count} waiting")
        if streaming_count > 0:
            parts.append(f"{streaming_count} streaming")
        active_line = f"[cyan]Active:[/cyan] [bold]{' + '.join(parts)}[/bold]" if parts else f"[cyan]Active:[/cyan] [bold]{active_count}[/bold]"
        lines.append(("rollup_active", active_line))

    ttfts = rollup_metrics['ttfts']
    if ttfts:
        avg_ttft = sum(ttfts) / len(ttfts)
        p10_ttft = percentile(ttfts, 10)
        p90_ttft = percentile(ttfts, 90)

        if p10_ttft is not None and p90_ttft is not None and len(ttfts) > 1:
            text = f"[cyan]TTFT:[/cyan] [bold]{avg_ttft:.1f}s[/bold] avg [dim](p10-p90: {p10_ttft:.1f}s-{p90_ttft:.1f}s)[/dim]"
        else:
            text = f"[cyan]TTFT:[/cyan] [bold]{avg_ttft:.1f}s[/bold] avg"
        lines.append(("rollup_ttft", text))

    streaming_times = rollup_metrics['streaming_times']
    if streaming_times:
        avg_streaming = sum(streaming_times) / len(streaming_times)
        p10_streaming = percentile(streaming_times, 10)
        p90_streaming = percentile(streaming_times, 90)

        if p10_streaming is not None and p90_streaming is not None and len(streaming_times) > 1:
            text = f"[cyan]Streaming:[/cyan] [bold]{avg_streaming:.1f}s[/bold] avg [dim](p10-p90: {p10_streaming:.1f}s-{p90_streaming:.1f}s)[/dim]"
        else:
            text = f"[cyan]Streaming:[/cyan] [bold]{avg_streaming:.1f}s[/bold] avg"
        lines.append(("rollup_streaming", text))

    token_count = rollup_metrics['token_count']
    if token_count > 0:
        avg_input = rollup_metrics['total_input_tokens'] / token_count
        avg_output = rollup_metrics['total_output_tokens'] / token_count
        token_line = f"[cyan]Tokens:[/cyan] [green]{avg_input:.0f}[/green] in → [blue]{avg_output:.0f}[/blue] out"

        if rollup_metrics['total_reasoning_tokens'] > 0:
            avg_reasoning = rollup_metrics['total_reasoning_tokens'] / token_count
            token_line += f" [dim](+[magenta]{avg_reasoning:.0f}[/magenta] reasoning)[/dim]"

        lines.append(("rollup_tokens", token_line))

    return lines
