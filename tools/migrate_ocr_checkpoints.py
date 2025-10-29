#!/usr/bin/env python3
"""
One-off migration script to fix OCR checkpoints in existing books.

Background:
- Old code marked OCR complete after PSMs finished, before vision selection
- New code requires both PSMs AND vision selection complete
- This script resets main OCR checkpoint to 'in_progress' if vision incomplete

Usage:
    python tools/migrate_ocr_checkpoints.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from infra.config import Config
from infra.storage.library import Library
from infra.storage.checkpoint import CheckpointManager


def migrate_book(scan_id: str, storage_root: Path) -> bool:
    """
    Migrate a single book's OCR checkpoint.

    Returns:
        True if checkpoint was reset, False if no action needed
    """
    # Check main OCR checkpoint
    main_checkpoint = CheckpointManager(
        scan_id=scan_id,
        stage='ocr',
        storage_root=storage_root
    )

    main_status = main_checkpoint.get_status()

    # Only process if main checkpoint is marked complete
    if main_status.get('status') != 'completed':
        print(f"  ⏭️  {scan_id}: Main checkpoint not complete - skipping")
        return False

    # Check vision selection checkpoint
    vision_checkpoint_file = storage_root / scan_id / 'ocr' / 'psm_selection' / '.checkpoint'

    if not vision_checkpoint_file.exists():
        # Vision selection never run - reset main checkpoint
        print(f"  🔄 {scan_id}: Vision checkpoint missing - resetting main checkpoint")

        # Reset status to 'in_progress' (preserves PSM sub-checkpoints)
        with main_checkpoint._lock:
            main_checkpoint._state['status'] = 'in_progress'
            if 'completed_at' in main_checkpoint._state:
                del main_checkpoint._state['completed_at']
            main_checkpoint._save_checkpoint()

        return True

    # Check if vision selection is complete
    vision_checkpoint = CheckpointManager(
        scan_id=scan_id,
        stage='ocr',
        storage_root=storage_root,
        output_dir='ocr/psm_selection'
    )

    vision_status = vision_checkpoint.get_status()

    if vision_status.get('status') != 'completed':
        # Vision incomplete - reset main checkpoint
        print(f"  🔄 {scan_id}: Vision incomplete - resetting main checkpoint")

        with main_checkpoint._lock:
            main_checkpoint._state['status'] = 'in_progress'
            if 'completed_at' in main_checkpoint._state:
                del main_checkpoint._state['completed_at']
            main_checkpoint._save_checkpoint()

        return True

    # Everything complete - no action needed
    print(f"  ✅ {scan_id}: Vision complete - no migration needed")
    return False


def main():
    """Migrate all books in library."""
    print("🔧 Migrating OCR checkpoints in library\n")

    storage_root = Config.book_storage_root
    library = Library(storage_root)

    all_books = library.list_books()
    print(f"Found {len(all_books)} books\n")

    migrated_count = 0

    for idx, book in enumerate(all_books, 1):
        scan_id = book['scan_id']
        print(f"[{idx}/{len(all_books)}] {scan_id}")

        try:
            if migrate_book(scan_id, storage_root):
                migrated_count += 1
        except Exception as e:
            print(f"  ❌ Error: {e}")
            continue

    print(f"\n✅ Migration complete")
    print(f"   Migrated: {migrated_count} books")
    print(f"   Skipped: {len(all_books) - migrated_count} books")


if __name__ == '__main__':
    main()
