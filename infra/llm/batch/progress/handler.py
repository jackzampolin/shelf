#!/usr/bin/env python3
"""Progress handler orchestration for LLM batch operations.

Ground truth sources:
- metrics_manager (metrics.json): Per-page detailed metrics
- batch_client.worker_pool.results: Success/failure status
- batch_client.get_active_requests(): Current request states
"""
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from infra.llm.batch import LLMBatchClient
    from infra.storage.metrics_manager import MetricsManager

from .rollups import calculate_rollups, format_rollup_lines
from .recent import build_recent_lines


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
        suffix = format_suffix(batch_stats, total_requests, elapsed)

        # Calculate rollup metrics from metrics.json
        rollup_metrics = calculate_rollups(metrics_manager, active, progress_bar._sub_lines)
        rollup_lines = format_rollup_lines(batch_stats, rollup_metrics)

        # Build recent completion lines from metrics.json + worker results
        recent_lines = build_recent_lines(
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


def format_suffix(batch_stats, total_requests: int, elapsed: float) -> str:
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
