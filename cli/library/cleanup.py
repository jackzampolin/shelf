"""
Cleanup script to remove unexpected directories and files from library.

Handles:
1. Unexpected directories (not registered stages or expected dirs)
2. Old timestamped log files (replaced by single append-only logs)
3. Legacy centralized logs directory (book/logs/ - now each stage has log.jsonl)
4. Empty files
5. macOS .DS_Store files
"""

import shutil
import re
from pathlib import Path
from typing import Dict, Any, List, Set
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from infra.pipeline.storage.library import Library
from infra.pipeline.registry import STAGE_NAMES
from infra.config import Config

console = Console()

# Expected non-stage directories in book directories
EXPECTED_NON_STAGES = {
    "source",       # Source PDF/images
    "web_logs",     # Web UI logs (may deprecate later)
}

# Pattern for old timestamped log files: stage_YYYYMMDD_HHMMSS.jsonl
TIMESTAMPED_LOG_PATTERN = re.compile(r'^.+_\d{8}_\d{6}\.jsonl$')

def get_expected_directories() -> Set[str]:
    """Get set of all expected directory names in a book."""
    return set(STAGE_NAMES) | EXPECTED_NON_STAGES


def get_directory_size(path: Path) -> int:
    """Get total size of directory in bytes."""
    if not path.exists():
        return 0

    total = 0
    try:
        for item in path.rglob('*'):
            if item.is_file():
                total += item.stat().st_size
    except Exception:
        pass

    return total


def format_size(size_bytes: int) -> str:
    """Format size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f}TB"


def cleanup_book(scan_id: str, storage_root: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Clean up unexpected directories for a single book.

    Args:
        scan_id: Book scan ID
        storage_root: Library storage root path
        dry_run: If True, only report what would be done

    Returns:
        Dict with cleanup status and details
    """
    book_dir = storage_root / scan_id

    if not book_dir.exists():
        return {
            "status": "skipped",
            "reason": "not_found",
            "scan_id": scan_id,
        }

    # Get expected directories
    expected_dirs = get_expected_directories()

    # Find unexpected directories
    unexpected_dirs = {}
    total_size = 0

    for item in book_dir.iterdir():
        # Skip files (only clean directories)
        if not item.is_dir():
            continue

        # Skip expected directories
        if item.name in expected_dirs:
            continue

        # Found an unexpected directory
        size = get_directory_size(item)
        unexpected_dirs[item.name] = {
            "path": item,
            "size": size,
        }
        total_size += size

    # Nothing to clean
    if not unexpected_dirs:
        return {
            "status": "skipped",
            "reason": "nothing_to_clean",
            "scan_id": scan_id,
        }

    if dry_run:
        return {
            "status": "would_clean",
            "scan_id": scan_id,
            "directories": list(unexpected_dirs.keys()),
            "total_size": total_size,
        }

    # Perform cleanup
    try:
        removed_dirs = []
        for dir_name, info in unexpected_dirs.items():
            shutil.rmtree(info["path"])
            removed_dirs.append(dir_name)

        return {
            "status": "success",
            "scan_id": scan_id,
            "removed_dirs": removed_dirs,
            "total_size": total_size,
        }

    except Exception as e:
        return {
            "status": "failed",
            "scan_id": scan_id,
            "error": str(e),
        }


def cleanup_root_stubs(storage_root: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Clean up unexpected root-level directories.

    Args:
        storage_root: Library storage root path
        dry_run: If True, only report what would be done

    Returns:
        Dict with cleanup status and details
    """
    # At the root level, we only expect book directories (which have metadata.json or source/ inside)
    # Any other directories are unexpected stubs
    found_stubs = {}
    total_size = 0

    for item in storage_root.iterdir():
        if not item.is_dir():
            continue

        # Check if it's a book directory (has metadata.json or source/ inside)
        is_book_dir = (item / "metadata.json").exists() or (item / "source").exists()

        if not is_book_dir:
            # This is an unexpected stub directory
            size = get_directory_size(item)
            found_stubs[item.name] = {
                "path": item,
                "size": size,
            }
            total_size += size

    if not found_stubs:
        return {
            "status": "skipped",
            "reason": "nothing_to_clean",
        }

    if dry_run:
        return {
            "status": "would_clean",
            "stubs": list(found_stubs.keys()),
            "total_size": total_size,
        }

    # Perform cleanup
    try:
        removed_stubs = []
        for stub_name, info in found_stubs.items():
            shutil.rmtree(info["path"])
            removed_stubs.append(stub_name)

        return {
            "status": "success",
            "removed_stubs": removed_stubs,
            "total_size": total_size,
        }

    except Exception as e:
        return {
            "status": "failed",
            "error": str(e),
        }


def cleanup_logs(storage_root: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Clean up legacy log files and directories.

    Removes:
    1. Legacy centralized logs directory (book/logs/) - now logs live in book/stage/log.jsonl
    2. Old timestamped log files (*_YYYYMMDD_HHMMSS.jsonl) anywhere
    3. Nested logs directories inside stages (book/stage/logs/)
    4. Empty log files

    Args:
        storage_root: Library storage root path
        dry_run: If True, only report what would be done

    Returns:
        Dict with cleanup stats
    """
    stats = {
        "legacy_logs_dirs": [],
        "timestamped_logs": [],
        "nested_logs_dirs": [],
        "empty_files": [],
        "total_size": 0,
    }

    # Find all log-related cleanup targets
    for book_dir in storage_root.iterdir():
        if not book_dir.is_dir() or book_dir.name.startswith('.'):
            continue

        # 1. Find legacy centralized logs directory (book/logs/)
        legacy_logs_dir = book_dir / "logs"
        if legacy_logs_dir.exists() and legacy_logs_dir.is_dir():
            size = get_directory_size(legacy_logs_dir)
            stats["legacy_logs_dirs"].append({
                "path": legacy_logs_dir,
                "size": size,
            })
            stats["total_size"] += size

        # 2. Find nested logs directories (book/stage/logs/)
        for stage_dir in book_dir.iterdir():
            if not stage_dir.is_dir():
                continue
            if stage_dir.name in EXPECTED_NON_STAGES or stage_dir.name == "logs":
                continue

            nested_logs = stage_dir / "logs"
            if nested_logs.exists() and nested_logs.is_dir():
                size = get_directory_size(nested_logs)
                stats["nested_logs_dirs"].append({
                    "path": nested_logs,
                    "size": size,
                })
                stats["total_size"] += size

        # 3. Find old timestamped log files anywhere in book
        for jsonl_file in book_dir.rglob("*.jsonl"):
            if TIMESTAMPED_LOG_PATTERN.match(jsonl_file.name):
                size = jsonl_file.stat().st_size
                stats["timestamped_logs"].append({
                    "path": jsonl_file,
                    "size": size,
                })
                stats["total_size"] += size

        # 4. Find empty .jsonl files (but not log.jsonl which may be legitimately empty)
        for jsonl_file in book_dir.rglob("*.jsonl"):
            if jsonl_file.stat().st_size == 0 and jsonl_file.name != "log.jsonl":
                stats["empty_files"].append({"path": jsonl_file, "size": 0})

    total_items = (
        len(stats["legacy_logs_dirs"]) +
        len(stats["timestamped_logs"]) +
        len(stats["nested_logs_dirs"]) +
        len(stats["empty_files"])
    )

    if total_items == 0:
        return {"status": "skipped", "reason": "nothing_to_clean"}

    if dry_run:
        return {
            "status": "would_clean",
            "legacy_logs_dirs_count": len(stats["legacy_logs_dirs"]),
            "timestamped_logs_count": len(stats["timestamped_logs"]),
            "nested_logs_dirs_count": len(stats["nested_logs_dirs"]),
            "empty_files_count": len(stats["empty_files"]),
            "total_size": stats["total_size"],
        }

    # Perform cleanup
    removed = {"legacy_logs_dirs": 0, "timestamped_logs": 0, "nested_logs_dirs": 0, "empty_files": 0}

    try:
        # Remove legacy logs directories
        for item in stats["legacy_logs_dirs"]:
            shutil.rmtree(item["path"])
            removed["legacy_logs_dirs"] += 1

        # Remove timestamped logs
        for item in stats["timestamped_logs"]:
            if item["path"].exists():  # May have been removed with legacy dir
                item["path"].unlink()
                removed["timestamped_logs"] += 1

        # Remove nested logs directories
        for item in stats["nested_logs_dirs"]:
            shutil.rmtree(item["path"])
            removed["nested_logs_dirs"] += 1

        # Remove empty files
        for item in stats["empty_files"]:
            if item["path"].exists():  # May have been removed with legacy dir
                item["path"].unlink()
                removed["empty_files"] += 1

        return {
            "status": "success",
            "removed_legacy_logs_dirs": removed["legacy_logs_dirs"],
            "removed_timestamped_logs": removed["timestamped_logs"],
            "removed_nested_logs_dirs": removed["nested_logs_dirs"],
            "removed_empty_files": removed["empty_files"],
            "total_size": stats["total_size"],
        }

    except Exception as e:
        return {
            "status": "partial",
            "removed_legacy_logs_dirs": removed["legacy_logs_dirs"],
            "removed_timestamped_logs": removed["timestamped_logs"],
            "removed_nested_logs_dirs": removed["nested_logs_dirs"],
            "removed_empty_files": removed["empty_files"],
            "error": str(e),
        }


def cleanup_ds_store(storage_root: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Remove .DS_Store files from library.

    Args:
        storage_root: Library storage root path
        dry_run: If True, only report what would be done

    Returns:
        Dict with cleanup stats
    """
    ds_files = list(storage_root.rglob(".DS_Store"))

    if not ds_files:
        return {"status": "skipped", "reason": "nothing_to_clean"}

    total_size = sum(f.stat().st_size for f in ds_files)

    if dry_run:
        return {
            "status": "would_clean",
            "count": len(ds_files),
            "total_size": total_size,
        }

    try:
        for f in ds_files:
            f.unlink()
        return {
            "status": "success",
            "removed_count": len(ds_files),
            "total_size": total_size,
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def cmd_cleanup(args):
    """Clean up unexpected directories from library."""
    library = Library(storage_root=Config.book_storage_root)
    scan_ids = library._scan_book_directories()

    expected_dirs = get_expected_directories()

    console.print(f"\n[bold]Library Cleanup Tool[/bold]")
    console.print(f"Found {len(scan_ids)} books in library")
    console.print(f"Expected directories: {', '.join(sorted(expected_dirs))}")
    console.print(f"Will remove: Any directories NOT in the expected list")

    if args.dry_run:
        console.print("[yellow]DRY RUN MODE - No changes will be made[/yellow]")

    console.print()

    # Clean up each book
    results = {
        "success": [],
        "skipped": [],
        "failed": [],
        "would_clean": [],
    }

    total_size_cleaned = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=False
    ) as progress:
        task = progress.add_task("Cleaning books...", total=len(scan_ids))

        for scan_id in scan_ids:
            progress.update(task, description=f"Processing {scan_id}...")

            result = cleanup_book(
                scan_id=scan_id,
                storage_root=library.storage_root,
                dry_run=args.dry_run,
            )

            status = result["status"]
            if status == "success":
                results["success"].append(result)
                total_size_cleaned += result["total_size"]
            elif status == "skipped":
                results["skipped"].append(result)
            elif status == "failed":
                results["failed"].append(result)
            elif status == "would_clean":
                results["would_clean"].append(result)
                total_size_cleaned += result["total_size"]

            progress.advance(task)

    # Clean up root stubs
    console.print("\n[bold]Cleaning root-level stubs...[/bold]")
    stub_result = cleanup_root_stubs(library.storage_root, dry_run=args.dry_run)

    if stub_result["status"] == "success":
        total_size_cleaned += stub_result["total_size"]
    elif stub_result["status"] == "would_clean":
        total_size_cleaned += stub_result["total_size"]

    # Clean up logs (timestamped files, nested dirs, empty files)
    console.print("\n[bold]Cleaning logs...[/bold]")
    logs_result = cleanup_logs(library.storage_root, dry_run=args.dry_run)

    if logs_result["status"] in ("success", "would_clean", "partial"):
        total_size_cleaned += logs_result.get("total_size", 0)

    # Clean up .DS_Store files
    console.print("\n[bold]Cleaning .DS_Store files...[/bold]")
    ds_result = cleanup_ds_store(library.storage_root, dry_run=args.dry_run)

    if ds_result["status"] in ("success", "would_clean"):
        total_size_cleaned += ds_result.get("total_size", 0)

    # Print summary
    console.print("\n[bold]Cleanup Summary[/bold]")
    console.print("=" * 80)

    if args.dry_run:
        # Dry run summary
        if results["would_clean"]:
            console.print(f"\n[cyan]Would clean {len(results['would_clean'])} books:[/cyan]")
            table = Table()
            table.add_column("Scan ID", style="cyan")
            table.add_column("Directories", style="yellow")
            table.add_column("Size", style="green")

            for r in results["would_clean"]:
                dirs = ", ".join(r["directories"])
                size = format_size(r["total_size"])
                table.add_row(r["scan_id"], dirs, size)

            console.print(table)

        if stub_result["status"] == "would_clean":
            console.print(f"\n[cyan]Would clean root stubs:[/cyan]")
            console.print(f"  Directories: {', '.join(stub_result['stubs'])}")
            console.print(f"  Size: {format_size(stub_result['total_size'])}")

        if logs_result["status"] == "would_clean":
            console.print(f"\n[cyan]Would clean logs:[/cyan]")
            console.print(f"  Legacy logs directories (book/logs/): {logs_result['legacy_logs_dirs_count']}")
            console.print(f"  Timestamped log files: {logs_result['timestamped_logs_count']}")
            console.print(f"  Nested logs directories: {logs_result['nested_logs_dirs_count']}")
            console.print(f"  Empty files: {logs_result['empty_files_count']}")
            console.print(f"  Size: {format_size(logs_result['total_size'])}")

        if ds_result["status"] == "would_clean":
            console.print(f"\n[cyan]Would clean .DS_Store files: {ds_result['count']}[/cyan]")

        if results["skipped"]:
            console.print(f"\n[yellow]Would skip {len(results['skipped'])} books (nothing to clean)[/yellow]")

        console.print(f"\n[bold green]Total space that would be reclaimed: {format_size(total_size_cleaned)}[/bold green]")

    else:
        # Actual cleanup summary
        if results["success"]:
            console.print(f"\n[green]Successfully cleaned {len(results['success'])} books:[/green]")
            table = Table()
            table.add_column("Scan ID", style="cyan")
            table.add_column("Removed", style="yellow")
            table.add_column("Size", style="green")

            for r in results["success"]:
                dirs = ", ".join(r["removed_dirs"])
                size = format_size(r["total_size"])
                table.add_row(r["scan_id"], dirs, size)

            console.print(table)

        if stub_result["status"] == "success":
            console.print(f"\n[green]Cleaned root stubs:[/green]")
            console.print(f"  Removed: {', '.join(stub_result['removed_stubs'])}")
            console.print(f"  Size: {format_size(stub_result['total_size'])}")

        if logs_result["status"] in ("success", "partial"):
            console.print(f"\n[green]Cleaned logs:[/green]")
            console.print(f"  Legacy logs directories removed: {logs_result.get('removed_legacy_logs_dirs', 0)}")
            console.print(f"  Timestamped log files removed: {logs_result.get('removed_timestamped_logs', 0)}")
            console.print(f"  Nested logs directories removed: {logs_result.get('removed_nested_logs_dirs', 0)}")
            console.print(f"  Empty files removed: {logs_result.get('removed_empty_files', 0)}")
            console.print(f"  Size: {format_size(logs_result.get('total_size', 0))}")
            if logs_result["status"] == "partial":
                console.print(f"  [yellow]Warning: {logs_result.get('error', 'unknown error')}[/yellow]")

        if ds_result["status"] == "success":
            console.print(f"\n[green]Cleaned .DS_Store files: {ds_result['removed_count']}[/green]")

        if results["skipped"]:
            console.print(f"\n[yellow]Skipped {len(results['skipped'])} books (nothing to clean)[/yellow]")

        if results["failed"]:
            console.print(f"\n[red]Failed to clean {len(results['failed'])} books:[/red]")
            for r in results["failed"]:
                console.print(f"  • {r['scan_id']}: {r['error']}")

        console.print(f"\n[bold green]Total space reclaimed: {format_size(total_size_cleaned)}[/bold green]")

    console.print()
