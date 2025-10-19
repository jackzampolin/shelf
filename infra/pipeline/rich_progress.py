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
import threading
from typing import Dict, List


class RichProgressBar:
    """Simple progress bar using Rich library.

    Drop-in replacement for ProgressBar that uses Rich internally.
    Handles sequential progress bars cleanly with transient mode.
    """

    def __init__(self, total: int, prefix: str = "", width: int = 40, unit: str = "items"):
        """Initialize progress bar.

        Args:
            total: Total number of items to process
            prefix: Text to show before the progress bar
            width: Width of the progress bar in characters
            unit: Unit name for rate display (default: "items")
        """
        self.total = total
        self.prefix = prefix
        self.unit = unit

        # Create custom columns to match current format
        self._progress = Progress(
            TextColumn(f"{prefix}{{task.description}}"),  # Prefix + description
            BarColumn(bar_width=width),
            TaskProgressColumn(),  # Shows "X/Y"
            TextColumn("•"),
            TextColumn("{task.fields[rate]}", justify="right"),
            TextColumn("•"),
            TimeRemainingColumn(),
            TextColumn("•"),
            TextColumn("{task.fields[suffix]}", justify="right"),
            transient=True,  # Disappears when context exits
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
        """Update progress bar.

        Args:
            current: Current number of items processed
            suffix: Optional suffix text to append
        """
        if not self._started:
            # Auto-start if used without context manager
            self.__enter__()

        # Calculate rate
        elapsed = self._progress.tasks[self._task_id].elapsed or 0.01
        rate = f"{current / elapsed:.1f} {self.unit}/sec" if elapsed > 0 else ""

        self._progress.update(
            self._task_id,
            completed=current,
            rate=rate,
            suffix=suffix
        )

    def finish(self, message: str = ""):
        """Finish progress and print message.

        Args:
            message: Optional completion message to display
        """
        if self._started:
            self.__exit__(None, None, None)
            self._started = False

        # Print completion message (progress bar is now cleared due to transient=True)
        if message:
            print(message)


class RichProgressBarHierarchical:
    """Progress bar with hierarchical sections support using Rich library.

    Supports:
    - Main progress bar
    - Hierarchical sections (e.g., "Running (3)", "Recent (5)")
    - Dynamic sub-items within sections
    - Thread-safe updates
    - Transient mode for clean sequential display
    """

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
            TextColumn(f"{prefix}{{task.description}}"),
            BarColumn(bar_width=width),
            TaskProgressColumn(),
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

                    section_node = tree.add(f"[bold]{title}[/bold]")

                    # Add items that have messages
                    valid_items = [item_id for item_id in items if item_id in self._sub_lines]

                    if not valid_items:
                        section_node.add("[dim](none)[/dim]")
                    else:
                        for item_id in valid_items:
                            msg = self._sub_lines[item_id]
                            section_node.add(msg)

                components.append(tree)

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
                                  total_requests: int, extract_error_code=None):
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
            extract_error_code: Optional function to format error messages (defaults to simple formatter)

        Returns:
            Event handler function that can be passed to batch_client.process_batch()

        Example:
            >>> progress = RichProgressBarHierarchical(total=100, prefix="   ", unit="pages")
            >>> on_event = progress.create_llm_event_handler(
            ...     batch_client=client,
            ...     start_time=time.time(),
            ...     model="anthropic/claude-sonnet-4",
            ...     total_requests=100
            ... )
            >>> results = client.process_batch(requests, on_event=on_event)
        """
        import time
        import sys
        # Import here to avoid circular dependencies
        from infra.llm.models import LLMEvent, RequestPhase

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

                    # Format: completed/total • pages/sec • elapsed time • cost
                    suffix = f"{batch_stats.completed}/{total_requests} • {batch_stats.requests_per_second:.1f} pages/sec • {elapsed:.0f}s • ${batch_stats.total_cost_usd:.2f}"

                    # Section 1: Running tasks (all executing requests)
                    executing = {req_id: status for req_id, status in active.items()
                                if status.phase == RequestPhase.EXECUTING}

                    running_ids = []
                    for req_id, status in sorted(executing.items()):
                        page_id = req_id.replace('page_', 'p')
                        elapsed_phase = status.phase_elapsed

                        # Check if we have streaming data for this request
                        # If yes, keep the streaming message (don't overwrite)
                        # If no, update "Waiting for response..." message with current elapsed time
                        current_msg = self._sub_lines.get(req_id, "")

                        # Only update if no message yet OR message is "Waiting for response" (not streaming)
                        if not current_msg or "Waiting for response" in current_msg:
                            if status.retry_count > 0:
                                msg = f"{page_id}: Waiting for response... ({elapsed_phase:.1f}s, retry {status.retry_count})"
                            else:
                                msg = f"{page_id}: Waiting for response... ({elapsed_phase:.1f}s)"
                            self.add_sub_line(req_id, msg)

                        running_ids.append(req_id)

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
                            # Show execution time (not total with queue time) and TTFT if available
                            ttft_str = f", TTFT {comp.ttft_seconds:.2f}s" if comp.ttft_seconds else ""
                            model_suffix = f" [{comp.model_used.split('/')[-1]}]" if comp.model_used and comp.model_used != model else ""
                            # Display cost in cents for better readability (0.0022 USD = 0.22¢)
                            cost_cents = comp.cost_usd * 100
                            msg = f"{page_id}: ✓ ({comp.execution_time_seconds:.1f}s{ttft_str}, {cost_cents:.2f}¢){model_suffix}"
                        else:
                            error_code = extract_error_code(comp.error_message)
                            # Show execution time, retry count and model if available
                            retry_suffix = f", retry {comp.retry_count}" if comp.retry_count > 0 else ""
                            model_suffix = f" [{comp.model_used.split('/')[-1]}]" if comp.model_used else ""
                            msg = f"{page_id}: ✗ ({comp.execution_time_seconds:.1f}s{retry_suffix}) - {error_code}{model_suffix}"

                        self.add_sub_line(req_id, msg)
                        recent_ids.append(req_id)

                    # Clean up old sub-lines that are no longer in any section
                    # Batch removal to avoid multiple re-renders
                    all_section_ids = set(running_ids + recent_ids)
                    to_remove = [line_id for line_id in self._sub_lines.keys()
                                if line_id not in all_section_ids]

                    for line_id in to_remove:
                        if line_id in self._sub_lines:
                            del self._sub_lines[line_id]
                    # Re-render happens in update() call below

                    # Set sections (creates hierarchical display)
                    self.set_section("running", f"Running ({len(running_ids)}):", running_ids)
                    self.set_section("recent", f"Recent ({len(recent_ids)}):", recent_ids)

                    # Update main bar (triggers re-render with sections)
                    self.update(event.completed, suffix=suffix)

                elif event.event_type == LLMEvent.RATE_LIMITED:
                    # Clear sections during rate limit pause
                    self.clear_sections()
                    self.set_status(f"⏸️  Rate limited, resuming in {event.eta_seconds:.0f}s")

            except Exception as e:
                # Don't let progress bar issues crash the worker thread
                import traceback
                error_msg = f"ERROR: Progress update failed: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
                print(error_msg, file=sys.stderr, flush=True)
                # Don't raise - let processing continue even if progress display fails

        return handle_event
