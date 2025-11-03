# 1. Think Data First (Ground Truth from Disk)

**Date:** 2025-10-30

**Status:** Accepted

## Context

Building software is fundamentally about data: what data, where data, when data, how data. The schema, the location, the existence, the size, the shape - these ARE the system.

Systems need to track progress for resumable batch processing. Traditional approaches use databases or checkpoint files to maintain state separate from the data itself.

## Decision

**The filesystem IS our database.** Always determine progress by checking what files exist on disk. After every operation we care about, write a file and associated metrics. Never trust state tracking - trust file existence.

Metrics (cost, time, tokens) are observations recorded alongside work, not drivers of resume logic.

## The Scale Argument

A book is hundreds of pages. That's **nothing** for computers. At this scale:
- Filesystem operations are instantaneous (`ls`, `cat`, `grep`)
- No database overhead (setup, migrations, queries)
- Simple tools provide visibility (just look in the directory)
- Bespoke Python system beats generic database

You need a database when dealing with **orders of magnitude more data** or complex relational queries. We have neither requirement.

## Philosophy: Simplicity, Power, Performance

The filesystem was designed for exactly this:
- **Simplicity:** `ls output/` shows what's done
- **Power:** Standard Unix tools work (grep, find, du)
- **Performance:** Hundreds of files is the comfort zone
- **Transparency:** Anyone can inspect the data

Compare to database approach:
- Need connection, credentials, migrations
- Can't inspect data without client
- Adds complexity for no benefit at this scale
- Harder to debug (WHERE is the data?)

## Consequences

**Enables:**
- **If-gate pattern:** Check disk → process → refresh → repeat
- **Cancel/resume anywhere:** No corrupted state possible
- **Easy debugging:** Just look at output directory
- **Web server integration:** Grab file, serve it (no queries)
- **Status as pure function:** `status = f(disk_contents)`

**Enables future:**
- Storage interface abstracts filesystem
- Could swap to MongoDB/document store for scale
- Would translate naturally (documents → documents)
- But filesystem is probably fine forever at book scale

## Implementation

See `pipeline/ocr/status.py` for reference implementation:

```python
def get_status(self, storage: BookStorage) -> Dict[str, Any]:
    # Get what exists on disk
    source_pages = source_stage.list_output_pages(extension="png")
    selection_map = self._load_selection_map(storage)

    # Calculate remaining from file existence
    selected_pages = set(int(k) for k in selection_map.keys())
    remaining_pages = sorted(all_pages - selected_pages)

    # Check artifacts on disk
    report_exists = (output_dir / "report.csv").exists()
```

Progress is **what files exist**, not what metrics say exists.

## Alternatives Considered

**Checkpoint files with serialized state:**
- Problem: State can drift from reality
- Problem: Partial writes corrupt state
- Rejected: Adds complexity, reduces reliability

**Database (Postgres/SQLite) tracking completed pages:**
- Problem: Overkill at this scale (hundreds of pages)
- Problem: Adds setup, migrations, connection handling
- Problem: Can't inspect data with `cat`
- Rejected: Wrong tool for the scale

**In-memory state with periodic saves:**
- Problem: Lose progress on crash
- Problem: State separate from data
- Rejected: Less reliable than file existence

## Why This Works

**At this scale, the filesystem IS a better database:**
- Transparency > query optimization
- Simplicity > feature richness
- File existence > state tracking
- Standard tools > custom clients

**The data tells you what's done.** Everything else is just watching it happen.
