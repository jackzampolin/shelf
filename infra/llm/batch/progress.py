#!/usr/bin/env python3
"""Batch-specific progress tracking and display formatting.

This module provides a self-contained PROGRESS event handler for LLM batch operations.
All data is derived from ground truth sources:
- metrics_manager (metrics.json): Per-page detailed metrics
- batch_client.worker_pool.results: Success/failure status
- batch_client.get_active_requests(): Current request states
"""
import time
import re
from typing import Dict, List, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from infra.llm.batch import LLMBatchClient
    from infra.storage.metrics_manager import MetricsManager

from .schemas import RequestPhase


def create_progress_handler(
    progress_bar,
    batch_client: 'LLMBatchClient',
    metrics_manager: Optional['MetricsManager'],
    model: str,
    total_requests: int,
    start_time: float
):
    """Create a PROGRESS event handler for batch operations.

    This handler is called periodically during batch processing and:
    1. Reads completed metrics from metrics.json (ground truth)
    2. Queries active request status from batch client
    3. Formats and displays rollup metrics + recent completions

    Args:
        progress_bar: RichProgressBarHierarchical instance with add_sub_line(), set_section(), update()
        batch_client: LLM batch client for querying active requests and results
        metrics_manager: Metrics manager for reading completed page metrics
        model: Primary model name for comparison
        total_requests: Total number of requests in batch
        start_time: Batch start timestamp

    Returns:
        Event handler function that processes PROGRESS events
    """

    def handle_progress_event(event):
        """Handle PROGRESS event - update rollup metrics and recent completions."""
        # Get current state
        active = batch_client.get_active_requests()
        batch_stats = batch_client.get_batch_stats(total_requests=total_requests)
        elapsed = time.time() - start_time

        # Format main progress bar suffix
        suffix = _format_suffix(batch_stats, total_requests, elapsed)

        # Calculate rollup metrics from metrics.json
        rollup_metrics = _calculate_rollups(metrics_manager, active, progress_bar._sub_lines)
        rollup_lines = _format_rollup_lines(batch_stats, rollup_metrics)

        # Build recent completion lines from metrics.json + worker results
        recent_lines = _build_recent_lines(
            batch_client.worker_pool.results,
            metrics_manager,
            model,
            max_recent=5
        )

        # Update progress bar with formatted sections
        rollup_ids = []
        for line_id, text in rollup_lines:
            progress_bar.add_sub_line(line_id, text)
            rollup_ids.append(line_id)

        recent_ids = []
        for line_id, text in recent_lines:
            progress_bar.add_sub_line(line_id, text)
            recent_ids.append(line_id)

        # Clean up old sub-lines
        all_section_ids = set(rollup_ids + recent_ids)
        to_remove = [lid for lid in progress_bar._sub_lines.keys() if lid not in all_section_ids]
        for lid in to_remove:
            if lid in progress_bar._sub_lines:
                del progress_bar._sub_lines[lid]

        # Set sections and update bar
        if rollup_ids:
            progress_bar.set_section("rollups", "Metrics:", rollup_ids)
        progress_bar.set_section("recent", f"Recent ({len(recent_ids)}):", recent_ids)
        progress_bar.update(event.completed, suffix=suffix)

    return handle_progress_event


def _format_suffix(batch_stats, total_requests: int, elapsed: float) -> str:
    """Format main progress bar suffix."""
    elapsed_mins = int(elapsed // 60)
    elapsed_secs = int(elapsed % 60)
    elapsed_str = f"{elapsed_mins}:{elapsed_secs:02d}"

    remaining = total_requests - batch_stats.completed
    if batch_stats.requests_per_second > 0 and remaining > 0:
        eta_seconds = remaining / batch_stats.requests_per_second
        eta_mins = int(eta_seconds // 60)
        eta_secs = int(eta_seconds % 60)
        eta_str = f"ETA {eta_mins}:{eta_secs:02d}"
    else:
        eta_str = ""

    if eta_str:
        return f"{batch_stats.completed}/{total_requests} • {elapsed_str} • {eta_str} • ${batch_stats.total_cost_usd:.2f}"
    else:
        return f"{batch_stats.completed}/{total_requests} • {elapsed_str} • ${batch_stats.total_cost_usd:.2f}"


def _calculate_rollups(metrics_manager, active_requests: Dict, sub_lines: Dict) -> Dict:
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


def _percentile(values: List[float], p: float) -> Optional[float]:
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


def _format_rollup_lines(batch_stats, rollup_metrics: Dict) -> List[Tuple[str, str]]:
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
        p10_ttft = _percentile(ttfts, 10)
        p90_ttft = _percentile(ttfts, 90)

        if p10_ttft is not None and p90_ttft is not None and len(ttfts) > 1:
            text = f"[cyan]TTFT:[/cyan] [bold]{avg_ttft:.1f}s[/bold] avg [dim](p10-p90: {p10_ttft:.1f}s-{p90_ttft:.1f}s)[/dim]"
        else:
            text = f"[cyan]TTFT:[/cyan] [bold]{avg_ttft:.1f}s[/bold] avg"
        lines.append(("rollup_ttft", text))

    streaming_times = rollup_metrics['streaming_times']
    if streaming_times:
        avg_streaming = sum(streaming_times) / len(streaming_times)
        p10_streaming = _percentile(streaming_times, 10)
        p90_streaming = _percentile(streaming_times, 90)

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


def _build_recent_lines(results_dict: Dict, metrics_manager, model: str, max_recent: int = 5) -> List[Tuple[str, str]]:
    """Build recent completion lines from worker results + metrics.json."""
    if not results_dict:
        return []

    # Sort by most recent (results dict should have completion order)
    sorted_results = sorted(
        results_dict.items(),
        key=lambda x: x[1].total_time_seconds,
        reverse=True
    )[:max_recent]

    lines = []
    for req_id, result in sorted_results:
        page_id = req_id.replace('page_', 'p')

        if result.success:
            # Try to get detailed metrics from metrics.json
            metrics = None
            if metrics_manager:
                try:
                    match = re.search(r'page_(\d{4})', req_id)
                    metrics_key = f"page_{match.group(1)}" if match else req_id
                    metrics = metrics_manager.get(metrics_key)
                except:
                    pass

            if metrics:
                parts = []
                if metrics.get('ttft_seconds'):
                    parts.append(f"FT {metrics['ttft_seconds']:.1f}s")
                if metrics.get('execution_time_seconds'):
                    parts.append(f"Exec {metrics['execution_time_seconds']:.1f}s")

                if metrics.get('prompt_tokens') is not None and metrics.get('completion_tokens') is not None:
                    tok_str = f"{metrics['prompt_tokens']}→{metrics['completion_tokens']}"
                    reasoning_tokens = metrics.get('reasoning_tokens', 0)
                    if reasoning_tokens > 0:
                        tok_str += f"+{reasoning_tokens}r"
                    parts.append(f"{tok_str} tok")
                elif metrics.get('tokens'):
                    parts.append(f"{metrics['tokens']} tok")

                cost_cents = metrics.get('cost_usd', 0) * 100
                parts.append(f"{cost_cents:.2f}¢")

                model_suffix = ""
                if metrics.get('model_used') and metrics['model_used'] != model:
                    model_suffix = f" [dim][{metrics['model_used'].split('/')[-1]}][/dim]"

                text = f"{page_id}: [bold green]✓[/bold green] [dim]({', '.join(parts)}){model_suffix}[/dim]"
            else:
                # Fallback to result data
                ttft_str = f", TTFT {result.ttft_seconds:.2f}s" if result.ttft_seconds else ""
                model_suffix = f" [dim][{result.model_used.split('/')[-1]}][/dim]" if result.model_used and result.model_used != model else ""
                cost_cents = (result.cost_usd or 0) * 100
                text = f"{page_id}: [bold green]✓[/bold green] [dim]({result.execution_time_seconds:.1f}s{ttft_str}, {cost_cents:.2f}¢){model_suffix}[/dim]"
        else:
            # Format failure
            error_code = _extract_error_code(result.error_message)
            retry_count = getattr(result.request, '_retry_count', 0)
            retry_suffix = f", retry {retry_count}" if retry_count > 0 else ""
            model_suffix = f" [dim][{result.model_used.split('/')[-1]}][/dim]" if result.model_used else ""
            text = f"{page_id}: [bold red]✗[/bold red] [dim]({result.execution_time_seconds:.1f}s{retry_suffix})[/dim] - [yellow]{error_code}[/yellow]{model_suffix}"

        lines.append((req_id, text))

    return lines


def _extract_error_code(error_message: str) -> str:
    """Extract readable error code from error message."""
    if not error_message:
        return "unknown"

    error_lower = error_message.lower()
    if '413' in error_message:
        return "413"
    elif '422' in error_message:
        return "422"
    elif '429' in error_message or 'rate_limit' in error_lower:
        return "429"
    elif '5' in error_message and 'server' in error_lower:
        return "5xx"
    elif '4' in error_message and ('client' in error_lower or 'error' in error_lower):
        return "4xx"
    elif 'timeout' in error_lower:
        return "timeout"
    else:
        return error_message[:20]


__all__ = ['create_progress_handler']
