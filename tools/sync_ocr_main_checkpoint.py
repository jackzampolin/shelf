#!/usr/bin/env python3
"""
Sync OCR main checkpoint from actual files on disk.

Rebuilds the main ocr/.checkpoint from:
- Existing PSM output files (ocr/psm{N}/page_*.json)
- Existing vision selection checkpoint (ocr/psm_selection/.checkpoint)

This is needed after the checkpoint consolidation refactor to migrate
from 4 separate checkpoints to a single main checkpoint with sub-stage tracking.

Usage:
    python tools/sync_ocr_main_checkpoint.py <scan-id>
    python tools/sync_ocr_main_checkpoint.py --all
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager


def sync_ocr_checkpoint(scan_id: str, storage_root: Path, psm_modes: list = [3, 4, 6]) -> Dict[str, Any]:
    """
    Sync main OCR checkpoint for a single book.

    Args:
        scan_id: Book scan ID
        storage_root: Library root directory
        psm_modes: List of PSM modes to check (default: [3, 4, 6])

    Returns:
        Dict with sync results
    """
    print(f"\n{'='*60}")
    print(f"Syncing: {scan_id}")
    print(f"{'='*60}")

    try:
        # Load book storage and metadata
        storage = BookStorage(scan_id=scan_id, storage_root=storage_root)
        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        if total_pages == 0:
            print(f"❌ No total_pages in metadata, skipping")
            return {'success': False, 'error': 'no_total_pages'}

        print(f"Total pages: {total_pages}")

        # Create main checkpoint manager
        checkpoint = CheckpointManager(
            scan_id=scan_id,
            stage='ocr',
            storage_root=storage_root
        )

        # Initialize with total_pages
        checkpoint.get_remaining_pages(total_pages=total_pages, resume=True)

        ocr_dir = storage.stage('ocr').output_dir

        # Track what we find
        psm_pages_found = {psm: set() for psm in psm_modes}
        vision_selections = {}

        # Scan PSM directories for page files
        for psm in psm_modes:
            psm_dir = ocr_dir / f'psm{psm}'
            if not psm_dir.exists():
                print(f"  PSM {psm}: directory not found")
                continue

            page_files = sorted(psm_dir.glob('page_*.json'))
            for page_file in page_files:
                # Extract page number from filename
                try:
                    page_num = int(page_file.stem.split('_')[1])
                    psm_pages_found[psm].add(page_num)
                except (ValueError, IndexError):
                    continue

            print(f"  PSM {psm}: {len(psm_pages_found[psm])} pages found")

        # Load vision selection checkpoint if it exists
        vision_checkpoint_file = ocr_dir / 'psm_selection' / '.checkpoint'
        if vision_checkpoint_file.exists():
            try:
                with open(vision_checkpoint_file, 'r') as f:
                    vision_data = json.load(f)

                # Extract vision_psm selections from page_metrics
                for page_str, metrics in vision_data.get('page_metrics', {}).items():
                    page_num = int(page_str)
                    # Vision checkpoint may have selected_psm in metrics
                    if 'selected_psm' in metrics:
                        vision_selections[page_num] = metrics['selected_psm']

                print(f"  Vision: {len(vision_selections)} selections found in checkpoint")
            except Exception as e:
                print(f"  Vision: Error loading checkpoint: {e}")

        # Also check psm_selection.json file if it exists
        selection_file = ocr_dir / 'psm_selection.json'
        if selection_file.exists():
            try:
                with open(selection_file, 'r') as f:
                    selection_data = json.load(f)

                for page_num_str, selection in selection_data.items():
                    page_num = int(page_num_str)
                    if 'selected_psm' in selection:
                        vision_selections[page_num] = selection['selected_psm']

                print(f"  Vision: {len(vision_selections)} total selections (including file)")
            except Exception as e:
                print(f"  Vision: Error loading selection file: {e}")

        # Now sync to main checkpoint using sub-stage API
        print("\n  Syncing to main checkpoint...")

        # Mark PSM completions
        for psm in psm_modes:
            for page_num in psm_pages_found[psm]:
                checkpoint.mark_substage_completed(
                    page_num=page_num,
                    substage=f'psm{psm}',
                    value=True,
                    cost_usd=0.0
                )

        # Mark vision selections
        for page_num, selected_psm in vision_selections.items():
            checkpoint.mark_substage_completed(
                page_num=page_num,
                substage='vision_psm',
                value=selected_psm,
                cost_usd=0.0
            )

        # Get final counts
        substages = [f'psm{psm}' for psm in psm_modes] + ['vision_psm']
        counts = checkpoint.get_substage_completion_counts(total_pages, substages)

        print("\n  Final checkpoint state:")
        for substage, count in counts.items():
            pct = (count / total_pages * 100) if total_pages > 0 else 0
            print(f"    {substage}: {count}/{total_pages} ({pct:.1f}%)")

        # Check if all complete
        all_complete = checkpoint.check_substages_complete(total_pages, substages)

        if all_complete:
            print("\n  ✅ All sub-stages complete!")
            checkpoint.mark_stage_complete()
        else:
            print(f"\n  ⏳ Incomplete - checkpoint status: in_progress")

        return {
            'success': True,
            'scan_id': scan_id,
            'total_pages': total_pages,
            'counts': counts,
            'all_complete': all_complete
        }

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Sync OCR main checkpoint from disk files')
    parser.add_argument('scan_id', nargs='?', help='Scan ID to sync (or --all for all books)')
    parser.add_argument('--all', action='store_true', help='Sync all books in library')
    parser.add_argument('--storage-root', type=Path,
                       default=Path.home() / 'Documents' / 'book_scans',
                       help='Storage root directory')

    args = parser.parse_args()

    if args.all:
        # Sync all books
        if not args.storage_root.exists():
            print(f"❌ Storage root not found: {args.storage_root}")
            sys.exit(1)

        # Find all book directories
        book_dirs = [d for d in args.storage_root.iterdir()
                    if d.is_dir() and (d / 'metadata.json').exists()]

        if not book_dirs:
            print(f"❌ No books found in {args.storage_root}")
            sys.exit(1)

        print(f"Found {len(book_dirs)} books to sync\n")

        results = []
        for book_dir in sorted(book_dirs):
            result = sync_ocr_checkpoint(book_dir.name, args.storage_root)
            results.append(result)

        # Summary
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        success_count = sum(1 for r in results if r.get('success'))
        complete_count = sum(1 for r in results if r.get('all_complete'))
        print(f"Total books: {len(results)}")
        print(f"Synced successfully: {success_count}")
        print(f"Fully complete: {complete_count}")
        print(f"Incomplete: {success_count - complete_count}")

    elif args.scan_id:
        # Sync single book
        result = sync_ocr_checkpoint(args.scan_id, args.storage_root)
        sys.exit(0 if result.get('success') else 1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
