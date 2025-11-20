"""
Cleanup script to remove unexpected directories from library.

Instead of hardcoding deprecated stages, this script:
1. Gets current registered stages from the registry
2. Defines expected non-stage directories (source, logs, etc.)
3. Removes anything that doesn't match either list
"""

import shutil
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
    "web_logs",     # Web UI logs
}

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

        if results["skipped"]:
            console.print(f"\n[yellow]Skipped {len(results['skipped'])} books (nothing to clean)[/yellow]")

        if results["failed"]:
            console.print(f"\n[red]Failed to clean {len(results['failed'])} books:[/red]")
            for r in results["failed"]:
                console.print(f"  • {r['scan_id']}: {r['error']}")

        console.print(f"\n[bold green]Total space reclaimed: {format_size(total_size_cleaned)}[/bold green]")

    console.print()
