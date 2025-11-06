"""Rich-based progress bar implementations.

Drop-in replacements for the custom ProgressBar class using the Rich library.
Provides two variants:
- RichProgressBar: Simple progress bar
- RichProgressBarHierarchical: Progress bar with hierarchical sections
"""

from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)
from rich.live import Live
from rich.console import Console, Group
from rich.tree import Tree
from rich.padding import Padding
import threading
from typing import Dict, List


class RichProgressBar:
    def __init__(self, total: int, prefix: str = "", width: int = 40, unit: str = "items"):
        self.total = total
        self.prefix = prefix
        self.unit = unit

        self._progress = Progress(
            TextColumn(f"{prefix}{{task.description}}"),
            BarColumn(bar_width=width),
            TaskProgressColumn(),
            TextColumn("•"),
            TextColumn("{task.fields[rate]}", justify="right"),
            TextColumn("•"),
            TimeRemainingColumn(),
            TextColumn("•"),
            TextColumn("{task.fields[suffix]}", justify="right"),
            transient=True,
        )

        self._task_id = None
        self._started = False

    def __enter__(self):
        self._progress.__enter__()
        self._task_id = self._progress.add_task(
            "",  # No description by default
            total=self.total,
            rate="",
            suffix=""
        )
        self._started = True
        return self

    def __exit__(self, *args):
        return self._progress.__exit__(*args)

    def update(self, current: int, suffix: str = ""):
        if not self._started:
            self.__enter__()

        elapsed = self._progress.tasks[self._task_id].elapsed or 0.01
        rate = f"{current / elapsed:.1f} {self.unit}/sec" if elapsed > 0 else ""

        self._progress.update(
            self._task_id,
            completed=current,
            rate=rate,
            suffix=suffix
        )

    def finish(self, message: str = ""):
        if self._started:
            self.__exit__(None, None, None)
            self._started = False

        # Print completion message (progress bar is now cleared due to transient=True)
        if message:
            print(message)


class RichProgressBarHierarchical:
    def __init__(self, total: int, prefix: str = "", width: int = 40, unit: str = "items"):
        """Initialize hierarchical progress bar.

        Args:
            total: Total number of items to process
            prefix: Text to show before the progress bar
            width: Width of the progress bar in characters
            unit: Unit name for rate display (default: "items")
        """
        self.total = total
        self.prefix = prefix
        self.unit = unit

        # Main progress bar
        self._progress = Progress(
            TextColumn(f"[bold cyan]{prefix}[/bold cyan]{{task.description}}"),
            BarColumn(
                bar_width=width,
                style="grey23",              # Unfilled background
                complete_style="green",       # Filled portion
                finished_style="bold green",  # Completed
            ),
            TaskProgressColumn(style="bold cyan"),
            TextColumn("[dim]•[/dim]"),
            TextColumn("{task.fields[suffix]}", justify="right"),
            transient=True
        )

        self._task_id = None
        self._live = None
        self._console = Console()

        # Hierarchical state
        self._sections: Dict[str, dict] = {}  # section_id -> {"title": str, "items": List[str]}
        self._sub_lines: Dict[str, str] = {}  # line_id -> message
        self._section_order: List[str] = []  # Track section order
        self._lock = threading.Lock()  # Thread safety for section updates

        self._started = False

    def __enter__(self):
        self._task_id = self._progress.add_task("", total=self.total, suffix="")
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=4,
            transient=True
        )
        self._live.__enter__()
        self._started = True
        return self

    def __exit__(self, *args):
        if self._live:
            self._live.__exit__(*args)
        self._started = False

    def _render(self):
        """Render progress bar + hierarchical sections."""
        with self._lock:
            components = [self._progress]

            # Add hierarchical sections if present
            if self._sections and self._section_order:
                tree = Tree("")

                for section_id in self._section_order:
                    if section_id not in self._sections:
                        continue

                    section_data = self._sections[section_id]
                    title = section_data["title"]
                    items = section_data["items"]

                    # Color-code section headers
                    if section_id == "rollups":
                        section_node = tree.add(f"[bold bright_cyan]{title}[/bold bright_cyan]")
                    elif section_id == "recent":
                        section_node = tree.add(f"[bold bright_yellow]{title}[/bold bright_yellow]")
                    else:
                        section_node = tree.add(f"[bold]{title}[/bold]")

                    # Add items that have messages
                    valid_items = [item_id for item_id in items if item_id in self._sub_lines]

                    if not valid_items:
                        section_node.add("[dim italic](none)[/dim italic]")
                    else:
                        for item_id in valid_items:
                            msg = self._sub_lines[item_id]
                            section_node.add(msg)

                # Add indentation to the tree
                components.append(Padding(tree, (0, 0, 0, 3)))

            return Group(*components)

    def update(self, current: int, suffix: str = ""):
        """Update progress bar.

        Args:
            current: Current number of items processed
            suffix: Optional suffix text to append
        """
        if not self._started:
            self.__enter__()

        self._progress.update(self._task_id, completed=current, suffix=suffix)

        # Refresh live display with updated sections
        if self._live:
            self._live.update(self._render())

    def add_sub_line(self, line_id: str, message: str):
        """Add or update a sub-status line.

        Args:
            line_id: Unique identifier for this status line
            message: Status message to display
        """
        with self._lock:
            self._sub_lines[line_id] = message

        # Trigger re-render
        if self._live:
            self._live.update(self._render())

    def remove_sub_line(self, line_id: str):
        """Remove a sub-status line.

        Args:
            line_id: Unique identifier of the line to remove
        """
        with self._lock:
            if line_id in self._sub_lines:
                del self._sub_lines[line_id]

        if self._live:
            self._live.update(self._render())

    def set_section(self, section_id: str, title: str, line_ids: List[str]):
        """Create or update a hierarchical section.

        Args:
            section_id: Unique identifier for this section
            title: Section header (e.g., "Running (3):")
            line_ids: List of line_ids to include in this section
        """
        with self._lock:
            self._sections[section_id] = {
                "title": title,
                "items": line_ids
            }

            # Track section order (add if new)
            if section_id not in self._section_order:
                self._section_order.append(section_id)

        # Trigger re-render
        if self._live:
            self._live.update(self._render())

    def clear_sections(self):
        """Remove all sections and return to flat display."""
        with self._lock:
            self._sections.clear()
            self._section_order.clear()

        if self._live:
            self._live.update(self._render())

    def set_status(self, message: str):
        """Display a temporary status message without updating progress.

        Useful for showing transient states like "Rate limited, waiting..."

        Args:
            message: Status message to display
        """
        # Update task description temporarily
        self._progress.update(self._task_id, description=message)

        if self._live:
            self._live.update(self._render())

    def finish(self, message: str = ""):
        """Clear progress bar and print completion message.

        Args:
            message: Optional completion message to display
        """
        if self._started:
            self.__exit__(None, None, None)

        if message:
            print(message)

    def create_llm_event_handler(self, batch_client, start_time: float, model: str,
                                  total_requests: int, metrics_manager=None, extract_error_code=None):
        """Create a standard LLM event handler for batch processing.

        Returns a configured event handler that displays:
        - FIRST_TOKEN events (time-to-first-token)
        - STREAMING events (real-time token updates)
        - PROGRESS events (running tasks + recent completions)
        - RATE_LIMITED events (pause notifications)

        Args:
            batch_client: LLMBatchClient instance for querying state
            start_time: Start time of the batch process (for elapsed calculation)
            model: Primary model name (for showing model suffix when different)
            total_requests: Total number of requests in batch
            metrics_manager: Optional MetricsManager for querying detailed metrics
            extract_error_code: Optional function to format error messages (defaults to simple formatter)

        Returns:
            Event handler function that can be passed to batch_client.process_batch()

        Example:
            >>> progress = RichProgressBarHierarchical(total=100, prefix="   ", unit="pages")
            >>> on_event = progress.create_llm_event_handler(
            ...     batch_client=client,
            ...     start_time=time.time(),
            ...     model="anthropic/claude-sonnet-4",
            ...     total_requests=100,
            ...     checkpoint=checkpoint
            ... )
            >>> results = client.process_batch(requests, on_event=on_event)
        """
        import time
        import sys
        # Import here to avoid circular dependencies
        from infra.llm.models import LLMEvent
        from infra.llm.batch.schemas import RequestPhase
        from infra.llm.batch.progress import (
            build_recent_completions,
            calculate_rollup_metrics,
            format_progress_suffix,
            format_rollup_lines,
            format_recent_completion_lines,
        )

        # Default error code extractor
        if extract_error_code is None:
            def extract_error_code(error_message: str) -> str:
                if not error_message:
                    return "unknown"
                error_lower = error_message.lower()
                if '413' in error_message:
                    return "413"
                elif '422' in error_message:
                    return "422"
                elif '429' in error_message:
                    return "429"
                elif '5' in error_message and 'server' in error_lower:
                    return "5xx"
                elif '4' in error_message and ('client' in error_lower or 'error' in error_lower):
                    return "4xx"
                elif 'timeout' in error_lower:
                    return "timeout"
                else:
                    return error_message[:20]

        def handle_event(event):
            """Handle LLM lifecycle events."""
            try:
                if event.event_type == LLMEvent.FIRST_TOKEN:
                    # First token received - show time-to-first-token
                    if event.message is not None:
                        self.add_sub_line(event.request_id, event.message)
                        # Trigger re-render
                        if hasattr(self, '_live') and self._live:
                            self._live.update(self._render())

                elif event.event_type == LLMEvent.STREAMING:
                    # Real-time streaming update for a single request
                    if event.message is not None:
                        self.add_sub_line(event.request_id, event.message)
                        # Trigger re-render
                        if hasattr(self, '_live') and self._live:
                            self._live.update(self._render())

                elif event.event_type == LLMEvent.PROGRESS:
                    # Query batch client for current state
                    active = batch_client.get_active_requests()
                    recent = batch_client.get_recent_completions()

                    # Update progress bar suffix
                    batch_stats = batch_client.get_batch_stats(total_requests=total_requests)
                    elapsed = time.time() - start_time

                    # Format elapsed time as mm:ss
                    elapsed_mins = int(elapsed // 60)
                    elapsed_secs = int(elapsed % 60)
                    elapsed_str = f"{elapsed_mins}:{elapsed_secs:02d}"

                    # Calculate ETA based on current throughput
                    remaining = total_requests - batch_stats.completed
                    if batch_stats.requests_per_second > 0 and remaining > 0:
                        eta_seconds = remaining / batch_stats.requests_per_second
                        eta_mins = int(eta_seconds // 60)
                        eta_secs = int(eta_seconds % 60)
                        eta_str = f"ETA {eta_mins}:{eta_secs:02d}"
                    else:
                        eta_str = ""

                    # Format: completed/total • elapsed time • ETA • total cost
                    if eta_str:
                        suffix = f"{batch_stats.completed}/{total_requests} • {elapsed_str} • {eta_str} • ${batch_stats.total_cost_usd:.2f}"
                    else:
                        suffix = f"{batch_stats.completed}/{total_requests} • {elapsed_str} • ${batch_stats.total_cost_usd:.2f}"

                    # Section 1: Rollups (aggregated metrics)
                    executing = {req_id: status for req_id, status in active.items()
                                if status.phase == RequestPhase.EXECUTING}

                    # Count active requests by state (waiting vs streaming)
                    waiting_count = 0
                    streaming_count = 0
                    for req_id in executing.keys():
                        msg = self._sub_lines.get(req_id, "")
                        if "Waiting for response" in msg or not msg:
                            waiting_count += 1
                        else:
                            streaming_count += 1

                    # Calculate aggregate metrics from ALL completed pages (session-wide, not just recent window)
                    # This provides stable stats throughout the entire run instead of only the last 10 seconds
                    ttfts = []
                    streaming_times = []
                    total_input_tokens = 0
                    total_output_tokens = 0
                    total_reasoning_tokens = 0
                    token_count = 0

                    if metrics_manager:
                        # Get all completed page metrics for session-wide statistics
                        all_metrics = metrics_manager.get_all()

                        for key, metrics in all_metrics.items():
                            # TTFT values
                            if metrics.get('ttft_seconds') is not None:
                                ttfts.append(metrics['ttft_seconds'])

                            # Streaming time (execution - ttft)
                            if metrics.get('execution_time_seconds') is not None and metrics.get('ttft_seconds') is not None:
                                streaming_time = metrics['execution_time_seconds'] - metrics['ttft_seconds']
                                if streaming_time > 0:
                                    streaming_times.append(streaming_time)

                            # Token counts (now broken out in metrics)
                            if metrics.get('prompt_tokens') is not None:
                                total_input_tokens += metrics.get('prompt_tokens', 0)
                                total_output_tokens += metrics.get('completion_tokens', 0)
                                total_reasoning_tokens += metrics.get('reasoning_tokens', 0)
                                token_count += 1

                    # Helper function to calculate percentiles
                    def percentile(values, p):
                        if not values:
                            return None
                        sorted_vals = sorted(values)
                        k = (len(sorted_vals) - 1) * p / 100
                        f = int(k)
                        c = min(f + 1, len(sorted_vals) - 1)
                        if f == c:
                            return sorted_vals[int(k)]
                        return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])

                    # Calculate statistics
                    avg_ttft = sum(ttfts) / len(ttfts) if ttfts else None
                    p10_ttft = percentile(ttfts, 10)
                    p90_ttft = percentile(ttfts, 90)

                    avg_streaming = sum(streaming_times) / len(streaming_times) if streaming_times else None
                    p10_streaming = percentile(streaming_times, 10)
                    p90_streaming = percentile(streaming_times, 90)

                    # Build rollup display
                    rollup_ids = []

                    # Throughput (pages/sec)
                    if batch_stats.requests_per_second > 0:
                        self.add_sub_line("rollup_throughput",
                            f"[cyan]Throughput:[/cyan] [bold]{batch_stats.requests_per_second:.1f}[/bold] [dim]pages/sec[/dim]")
                        rollup_ids.append("rollup_throughput")

                    # Average cost per request
                    if batch_stats.completed > 0:
                        avg_cost_cents = (batch_stats.total_cost_usd / batch_stats.completed) * 100
                        self.add_sub_line("rollup_avg_cost",
                            f"[cyan]Avg cost:[/cyan] [bold yellow]{avg_cost_cents:.2f}¢[/bold yellow][dim]/page[/dim]")
                        rollup_ids.append("rollup_avg_cost")

                    # Active requests breakdown (waiting vs streaming)
                    active_count = len(executing)
                    if active_count > 0:
                        parts = []
                        if waiting_count > 0:
                            parts.append(f"{waiting_count} waiting")
                        if streaming_count > 0:
                            parts.append(f"{streaming_count} streaming")
                        active_line = f"[cyan]Active:[/cyan] [bold]{' + '.join(parts)}[/bold]" if parts else f"[cyan]Active:[/cyan] [bold]{active_count}[/bold]"
                        self.add_sub_line("rollup_active", active_line)
                        rollup_ids.append("rollup_active")

                    # TTFT stats (avg with p10/p90 band)
                    if avg_ttft is not None:
                        if p10_ttft is not None and p90_ttft is not None and len(ttfts) > 1:
                            self.add_sub_line("rollup_ttft",
                                f"[cyan]TTFT:[/cyan] [bold]{avg_ttft:.1f}s[/bold] avg [dim](p10-p90: {p10_ttft:.1f}s-{p90_ttft:.1f}s)[/dim]")
                        else:
                            self.add_sub_line("rollup_ttft", f"[cyan]TTFT:[/cyan] [bold]{avg_ttft:.1f}s[/bold] avg")
                        rollup_ids.append("rollup_ttft")

                    # Streaming time (execution - ttft) with p10/p90 band
                    if avg_streaming is not None:
                        if p10_streaming is not None and p90_streaming is not None and len(streaming_times) > 1:
                            self.add_sub_line("rollup_streaming",
                                f"[cyan]Streaming:[/cyan] [bold]{avg_streaming:.1f}s[/bold] avg [dim](p10-p90: {p10_streaming:.1f}s-{p90_streaming:.1f}s)[/dim]")
                        else:
                            self.add_sub_line("rollup_streaming", f"[cyan]Streaming:[/cyan] [bold]{avg_streaming:.1f}s[/bold] avg")
                        rollup_ids.append("rollup_streaming")

                    # Token throughput (recent window)
                    if token_count > 0:
                        avg_input = total_input_tokens / token_count
                        avg_output = total_output_tokens / token_count
                        token_line = f"[cyan]Tokens:[/cyan] [green]{avg_input:.0f}[/green] in → [blue]{avg_output:.0f}[/blue] out"
                        if total_reasoning_tokens > 0:
                            avg_reasoning = total_reasoning_tokens / token_count
                            token_line += f" [dim](+[magenta]{avg_reasoning:.0f}[/magenta] reasoning)[/dim]"
                        self.add_sub_line("rollup_tokens", token_line)
                        rollup_ids.append("rollup_tokens")

                    # Section 2: Last 5 events (successes, failures, retries - sorted by most recent first)
                    recent_sorted = sorted(
                        recent.items(),
                        key=lambda x: x[1].cycles_remaining,
                        reverse=True
                    )[:5]

                    recent_ids = []
                    for req_id, comp in recent_sorted:
                        page_id = req_id.replace('page_', 'p')

                        if comp.success:
                            # Query metrics_manager for detailed metrics if available
                            metrics = None
                            if metrics_manager:
                                try:
                                    # Extract simple page key from request ID
                                    # Handles formats: "page_0042", "page_0042_vision", "stage1_page_0042", etc.
                                    # All store metrics under "page_XXXX"
                                    import re
                                    match = re.search(r'page_(\d{4})', req_id)
                                    if match:
                                        metrics_key = f"page_{match.group(1)}"
                                    else:
                                        metrics_key = req_id
                                    metrics = metrics_manager.get(metrics_key)
                                except:
                                    pass  # Fall back to basic display if metrics unavailable

                            # Display format: FT (first token), Exec (execution time), input→output tok, cost
                            if metrics:
                                # Build compact metrics display
                                parts = []
                                if metrics.get('ttft_seconds'):
                                    parts.append(f"FT {metrics['ttft_seconds']:.1f}s")
                                if metrics.get('execution_time_seconds'):
                                    parts.append(f"Exec {metrics['execution_time_seconds']:.1f}s")
                                # Show input→output token format with reasoning tokens if available
                                if metrics.get('prompt_tokens') is not None and metrics.get('completion_tokens') is not None:
                                    tok_str = f"{metrics['prompt_tokens']}→{metrics['completion_tokens']}"
                                    # Add reasoning tokens if present
                                    reasoning_tokens = metrics.get('reasoning_tokens', 0)
                                    if reasoning_tokens > 0:
                                        tok_str += f"+{reasoning_tokens}r"
                                    parts.append(f"{tok_str} tok")
                                elif metrics.get('tokens'):
                                    parts.append(f"{metrics['tokens']} tok")
                                cost_cents = metrics.get('cost_usd', 0) * 100
                                parts.append(f"{cost_cents:.2f}¢")

                                # Model suffix if different
                                model_suffix = ""
                                if metrics.get('model_used') and metrics['model_used'] != model:
                                    model_suffix = f" [dim][{metrics['model_used'].split('/')[-1]}][/dim]"

                                msg = f"{page_id}: [bold green]✓[/bold green] [dim]({', '.join(parts)}){model_suffix}[/dim]"
                            else:
                                # Fallback to basic display without checkpoint metrics
                                ttft_str = f", TTFT {comp.ttft_seconds:.2f}s" if comp.ttft_seconds else ""
                                model_suffix = f" [dim][{comp.model_used.split('/')[-1]}][/dim]" if comp.model_used and comp.model_used != model else ""
                                cost_cents = comp.cost_usd * 100
                                msg = f"{page_id}: [bold green]✓[/bold green] [dim]({comp.execution_time_seconds:.1f}s{ttft_str}, {cost_cents:.2f}¢){model_suffix}[/dim]"
                        else:
                            error_code = extract_error_code(comp.error_message)
                            # Show execution time, retry count and model if available
                            retry_suffix = f", retry {comp.retry_count}" if comp.retry_count > 0 else ""
                            model_suffix = f" [dim][{comp.model_used.split('/')[-1]}][/dim]" if comp.model_used else ""
                            msg = f"{page_id}: [bold red]✗[/bold red] [dim]({comp.execution_time_seconds:.1f}s{retry_suffix})[/dim] - [yellow]{error_code}[/yellow]{model_suffix}"

                        self.add_sub_line(req_id, msg)
                        recent_ids.append(req_id)

                    # Clean up old sub-lines that are no longer in any section
                    # Batch removal to avoid multiple re-renders
                    all_section_ids = set(rollup_ids + recent_ids)
                    to_remove = [line_id for line_id in self._sub_lines.keys()
                                if line_id not in all_section_ids]

                    for line_id in to_remove:
                        if line_id in self._sub_lines:
                            del self._sub_lines[line_id]
                    # Re-render happens in update() call below

                    # Set sections (creates hierarchical display)
                    if rollup_ids:
                        self.set_section("rollups", "Metrics:", rollup_ids)
                    self.set_section("recent", f"Recent ({len(recent_ids)}):", recent_ids)

                    # Update main bar (triggers re-render with sections)
                    self.update(event.completed, suffix=suffix)

                elif event.event_type == LLMEvent.RATE_LIMITED:
                    # Keep rollup metrics visible during rate limit, just update status
                    # Don't clear sections - users want to see the current stats while waiting
                    self.set_status(f"⏸️  Rate limited, resuming in {event.eta_seconds:.0f}s")

            except Exception as e:
                # Don't let progress bar issues crash the worker thread
                import traceback
                error_msg = f"ERROR: Progress update failed: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
                print(error_msg, file=sys.stderr, flush=True)
                # Don't raise - let processing continue even if progress display fails

        return handle_event
