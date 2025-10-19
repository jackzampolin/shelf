# Rich Library Integration Plan

## Executive Summary

Replace the custom `ProgressBar` class in `infra/pipeline/progress.py` with Rich library's Progress API. Rich provides:
- Built-in thread safety
- Cleaner ANSI handling (no manual escape sequences)
- Extensive customization via columns
- Transient mode for sequential progress bars
- Live display with Group for hierarchical sections

## Current Usage Analysis

### Usage Patterns Found

1. **Sequential progress bars** (loading → processing)
   - Used in `pipeline/2_correction/__init__.py`, `pipeline/3_label/__init__.py`
   - Pattern: One progress bar finishes, then another starts

2. **Hierarchical sections** with sub-lines
   - Used in LLM batch processing
   - Shows "Running (3)" and "Recent (5)" sections
   - Each section has dynamic sub-items

3. **Thread-safe updates** from ThreadPoolExecutor
   - Multiple threads call `progress.update()` concurrently
   - Updates from LLM batch client callbacks

4. **Custom suffix** for metadata
   - Pattern: `progress.update(50, suffix="$2.50 | 75% rate")`

5. **Status messages** (transient)
   - Pattern: `progress.set_status("Rate limited, resuming in 10s")`

## Rich API Mapping

### Core API Components

| Current Method | Rich Equivalent | Notes |
|----------------|-----------------|-------|
| `ProgressBar(total=100, prefix="   ", width=40, unit="pages")` | `Progress(...)` with custom columns | Use context manager |
| `progress.update(current, suffix="...")` | `progress.update(task_id, completed=current, **fields)` | Use custom fields for suffix |
| `progress.finish("✓ Done")` | Exit context manager + print | Transient mode clears automatically |
| `progress.add_sub_line(id, msg)` | Use `Console.print()` via `progress.console` OR use `Live` + `Group` | Depends on complexity |
| `progress.set_section(id, title, items)` | Use `Live` + `Group` + custom rendering | For hierarchical display |
| `progress.set_status(msg)` | `progress.update(task_id, description=msg)` | Or use `progress.console.print()` |

### Thread Safety

Rich Progress is **thread-safe by default**. The `Task` class uses `RLock` internally:
- Safe to call `progress.update()` from multiple threads
- Safe to update multiple tasks concurrently
- No additional locking needed (unlike our custom implementation)

## Integration Approach

### Strategy: Wrapper Class (Recommended)

**Why:** Minimize disruption to existing code while gaining Rich's benefits.

Create a `RichProgressBar` wrapper that:
1. Implements the same API as current `ProgressBar`
2. Internally uses Rich's `Progress` class
3. Handles hierarchical sections using `Live` + `Group`
4. Provides transient mode for sequential bars

### Alternative: Direct Rich Usage

**Pros:** Full control, no wrapper overhead
**Cons:** Requires changes to all 7 call sites, more complex migration

**Recommendation:** Start with wrapper, then optionally refactor call sites later.

## Implementation Plan

### Phase 1: Simple Progress Bar (No Hierarchical Sections)

**Use Case:** Simple sequential progress bars (tools/add.py, pipeline/1_ocr)

```python
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    TimeElapsedColumn
)

class RichProgressBar:
    """Drop-in replacement for ProgressBar using Rich library."""

    def __init__(self, total: int, prefix: str = "", width: int = 40, unit: str = "items"):
        self.total = total
        self.prefix = prefix
        self.unit = unit

        # Create custom columns to match current format
        self._progress = Progress(
            TextColumn(f"{prefix}[progress.description]"),  # Prefix + description
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
        """Update progress bar."""
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
        """Finish progress and print message."""
        if self._started:
            self.__exit__(None, None, None)
            self._started = False

        # Print completion message (progress bar is now cleared due to transient=True)
        if message:
            print(message)

# Usage example (backward compatible)
with RichProgressBar(total=100, prefix="   ", width=40, unit="pages") as progress:
    for i in range(100):
        progress.update(i + 1, suffix="$2.50")

progress.finish("   ✓ 100 pages processed")
```

### Phase 2: Hierarchical Sections (LLM Batch Processing)

**Use Case:** pipeline/2_correction, pipeline/3_label with running/recent sections

**Approach:** Use `Live` + `Group` + `Panel` for hierarchical display

```python
from rich.progress import Progress, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich.live import Live
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree
import threading
from typing import Dict, List

class RichProgressBarHierarchical:
    """Rich-based progress bar with hierarchical sections support."""

    def __init__(self, total: int, prefix: str = "", width: int = 40, unit: str = "items"):
        self.total = total
        self.prefix = prefix
        self.unit = unit

        # Main progress bar
        self._progress = Progress(
            TextColumn(f"{prefix}[progress.description]"),
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
            if self._sections:
                tree = Tree("")

                for section_id, section_data in self._sections.items():
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
        """Update progress bar."""
        if not self._started:
            self.__enter__()

        self._progress.update(self._task_id, completed=current, suffix=suffix)

        # Refresh live display with updated sections
        if self._live:
            self._live.update(self._render())

    def add_sub_line(self, line_id: str, message: str):
        """Add or update a sub-status line."""
        with self._lock:
            self._sub_lines[line_id] = message

        # Trigger re-render
        if self._live:
            self._live.update(self._render())

    def remove_sub_line(self, line_id: str):
        """Remove a sub-status line."""
        with self._lock:
            if line_id in self._sub_lines:
                del self._sub_lines[line_id]

        if self._live:
            self._live.update(self._render())

    def set_section(self, section_id: str, title: str, line_ids: List[str]):
        """Create or update a hierarchical section."""
        with self._lock:
            self._sections[section_id] = {
                "title": title,
                "items": line_ids
            }

        # Trigger re-render
        if self._live:
            self._live.update(self._render())

    def clear_sections(self):
        """Remove all sections."""
        with self._lock:
            self._sections.clear()

        if self._live:
            self._live.update(self._render())

    def set_status(self, message: str):
        """Display a temporary status message."""
        # Update task description temporarily
        self._progress.update(self._task_id, description=message)

        if self._live:
            self._live.update(self._render())

    def finish(self, message: str = ""):
        """Finish progress and print message."""
        if self._started:
            self.__exit__(None, None, None)

        if message:
            print(message)

# Usage example (matches current API)
with RichProgressBarHierarchical(total=100, prefix="   ", width=40, unit="pages") as progress:
    progress.update(0, suffix="starting...")

    # Simulate batch processing
    progress.add_sub_line("page_0001", "p0001: Executing... (2.3s)")
    progress.add_sub_line("page_0002", "p0002: Executing... (1.8s)")

    progress.set_section("running", "Running (2):", ["page_0001", "page_0002"])
    progress.update(50, suffix="$2.50")

    # Simulate completion
    progress.remove_sub_line("page_0001")
    progress.add_sub_line("page_0003", "p0003: ✓ (1.5s, $0.0023)")
    progress.set_section("running", "Running (1):", ["page_0002"])
    progress.set_section("recent", "Recent (1):", ["page_0003"])
    progress.update(75, suffix="$3.75")

progress.finish("   ✓ 100 pages processed")
```

### Phase 3: Sequential Progress Bars

**Pattern:** Load progress finishes, then processing progress starts

```python
# Current pattern (works with transient=True)
with RichProgressBar(total=100, prefix="   ", width=40, unit="pages") as load_progress:
    for i in range(100):
        load_progress.update(i + 1, suffix=f"{i + 1} loaded")

load_progress.finish("   ✓ 100 pages loaded in 5.2s")

# Second progress bar starts on next line (previous is cleared)
with RichProgressBar(total=100, prefix="   ", width=40, unit="pages") as process_progress:
    for i in range(100):
        process_progress.update(i + 1, suffix=f"${i * 0.01:.2f}")

process_progress.finish("   ✓ 100 pages processed in 45.3s")
```

**Key:** The `transient=True` parameter ensures the first progress bar disappears completely when finished, leaving only the completion message. The second progress bar starts fresh.

## Migration Strategy

### Step 1: Create Wrapper (1 file)

Create `/Users/johnzampolin/go/src/github.com/jackzampolin/scanshelf/infra/pipeline/rich_progress.py`:

```python
"""Rich-based progress bar implementations."""

# Include RichProgressBar and RichProgressBarHierarchical from examples above
```

### Step 2: Update Imports (7 files)

Replace:
```python
from infra.pipeline.progress import ProgressBar
```

With:
```python
from infra.pipeline.rich_progress import RichProgressBar as ProgressBar
# OR for hierarchical sections:
from infra.pipeline.rich_progress import RichProgressBarHierarchical as ProgressBar
```

**Files to update:**
1. `tools/add.py` - Simple progress (use `RichProgressBar`)
2. `pipeline/1_ocr/__init__.py` - Simple progress (use `RichProgressBar`)
3. `pipeline/2_correction/__init__.py` - Hierarchical (use `RichProgressBarHierarchical`)
4. `pipeline/3_label/__init__.py` - Hierarchical (use `RichProgressBarHierarchical`)

### Step 3: Testing

Test each usage pattern:
1. Simple progress bar (tools/add.py)
2. Sequential progress bars (pipeline/2_correction - loading then processing)
3. Hierarchical sections with thread-safe updates (pipeline/2_correction LLM batch)

### Step 4: Cleanup

Once validated:
1. Delete `infra/pipeline/progress.py`
2. Update any remaining references

## Rich Library Installation

Add to `pyproject.toml`:
```toml
[project]
dependencies = [
    # ... existing dependencies ...
    "rich>=13.0.0",
]
```

Then run:
```bash
uv pip install rich
```

## Gotchas and Limitations

### 1. Context Manager Required

Rich Progress works best as a context manager. Our wrapper handles this:
```python
# Don't need explicit with statement (wrapper handles it)
progress = RichProgressBar(total=100)
progress.update(50)
progress.finish()
```

### 2. Transient Mode Clears Everything

When `transient=True`, the **entire** progress display disappears on exit. This is perfect for sequential progress bars but means completion messages must be printed separately.

### 3. Live Display Limitations

Only one `Live` can be active at a time. This is fine for our use case since we have:
- Sequential progress bars (one at a time)
- Single hierarchical display (one Live wrapping progress + sections)

### 4. Thread Safety on Rendering

While Rich's `Progress.update()` is thread-safe, our custom `_render()` method needs locking when accessing `_sections` and `_sub_lines` dictionaries. The wrapper handles this with `self._lock`.

### 5. Refresh Rate

Rich defaults to 10 refreshes/second. We use 4 for LLM batch processing:
```python
Live(self._render(), refresh_per_second=4)
```

This reduces flicker while still being responsive.

## Benefits Over Current Implementation

1. **No manual ANSI codes** - Rich handles all cursor positioning
2. **Thread-safe by default** - No need for manual locking on updates
3. **Transient mode** - Clean sequential progress bars
4. **Better Unicode support** - Handles emoji and box-drawing characters
5. **Extensible** - Easy to add spinners, multiple bars, etc.
6. **Maintained** - Active library with regular updates
7. **Less buggy** - Current implementation has cursor positioning issues

## Example: Complete Real-World Usage

Here's how pipeline/2_correction would use it:

```python
from infra.pipeline.rich_progress import RichProgressBarHierarchical

# Loading phase
with RichProgressBarHierarchical(total=len(pages), prefix="   ", width=40, unit="pages") as load_progress:
    load_progress.update(0, suffix="loading...")

    # ... parallel loading with ThreadPoolExecutor ...

    with load_lock:
        completed_loads += 1
        load_progress.update(completed_loads, suffix=f"{len(requests)} loaded")

load_progress.finish(f"   ✓ {len(requests)} pages loaded in {load_elapsed:.1f}s")

# Processing phase
with RichProgressBarHierarchical(total=len(requests), prefix="   ", width=40, unit="pages") as progress:
    progress.update(0, suffix="starting...")

    # ... batch processing ...

    # In event handler (called from worker thread):
    def handle_batch_event(event: LLMEvent):
        if event.event_type == LLMEvent.BATCH_UPDATE:
            # Update sub-lines
            for req_id, status in running.items():
                msg = f"{req_id}: Executing... ({status.phase_elapsed:.1f}s)"
                progress.add_sub_line(req_id, msg)

            # Update sections
            progress.set_section("running", f"Running ({len(running)}):", list(running.keys()))
            progress.set_section("recent", f"Recent ({len(recent)}):", list(recent.keys())[:5])

            # Update main progress
            progress.update(event.completed, suffix=f"${event.cost_usd:.2f}")

        elif event.event_type == LLMEvent.RATE_LIMITED:
            progress.clear_sections()
            progress.set_status(f"⏸️  Rate limited, resuming in {event.eta_seconds:.0f}s")

progress.finish(f"   ✓ {batch_stats.completed}/{len(requests)} pages corrected in {correction_elapsed:.1f}s")
```

## Conclusion

**Recommendation:** Implement the wrapper approach (RichProgressBar and RichProgressBarHierarchical) to get:
- Drop-in replacement (minimal code changes)
- Rich library benefits (thread safety, clean rendering)
- Backward-compatible API
- Easy migration path

The wrapper isolates Rich-specific code, making it easy to:
1. Test incrementally
2. Rollback if needed
3. Refactor call sites later

**Estimated effort:**
- Create wrapper: 2-3 hours
- Update imports + test: 1-2 hours
- Total: 3-5 hours

**Risk:** Low - wrapper preserves existing API, Rich is battle-tested library.
