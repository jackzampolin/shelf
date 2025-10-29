#!/usr/bin/env python3
"""
Sync OCR main checkpoint with PSM sub-checkpoint states.

Problem:
- PSM checkpoints (ocr/psm3/.checkpoint, etc.) have page tracking
- Main checkpoint (ocr/.checkpoint) is empty (total_pages=0, status=not_started)
- This causes sweep to think OCR hasn't run

Solution:
- Scan actual page files in PSM directories
- Read PSM checkpoint states
- Aggregate into main checkpoint
- Set total_pages from metadata
- Update main checkpoint status based on sub-stage completion

Usage:
    python tools/sync_ocr_checkpoints.py
"""

import sys
import json
from pathlib import Path
from typing import Dict, Set

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from infra.config import Config
from infra.storage.library import Library
from infra.storage.checkpoint import CheckpointManager


def scan_psm_files(book_dir: Path, psm: int) -> Set[int]:
    """Scan actual page files in PSM directory."""
    psm_dir = book_dir / 'ocr' / f'psm{psm}'
    if not psm_dir.exists():
        return set()

    pages = set()
    for file in psm_dir.glob('page_*.json'):
        try:
            page_num = int(file.stem.split('_')[1])
            pages.add(page_num)
        except (ValueError, IndexError):
            continue

    return pages


def sync_book(scan_id: str, storage_root: Path, psm_modes: list = [3, 4, 6]) -> Dict:
    """
    Sync main OCR checkpoint with PSM sub-checkpoints and actual files.

    Returns:
        Dict with sync results
    """
    book_dir = storage_root / scan_id

    # Load metadata for total_pages
    metadata_file = book_dir / 'metadata.json'
    if not metadata_file.exists():
        return {'error': 'No metadata.json'}

    metadata = json.loads(metadata_file.read_text())
    total_pages = metadata.get('total_pages', 0)

    if total_pages == 0:
        return {'error': 'total_pages not set in metadata'}

    # Scan actual files and PSM checkpoints
    psm_states = {}

    for psm in psm_modes:
        # Scan actual files
        actual_pages = scan_psm_files(book_dir, psm)

        # Load PSM checkpoint if exists
        psm_checkpoint_file = book_dir / 'ocr' / f'psm{psm}' / '.checkpoint'
        checkpoint_pages = set()
        checkpoint_status = 'not_started'

        if psm_checkpoint_file.exists():
            try:
                checkpoint_data = json.loads(psm_checkpoint_file.read_text())
                checkpoint_pages = set(int(k) for k in checkpoint_data.get('page_metrics', {}).keys())
                checkpoint_status = checkpoint_data.get('status', 'not_started')
            except:
                pass

        psm_states[psm] = {
            'actual_files': len(actual_pages),
            'checkpoint_pages': len(checkpoint_pages),
            'checkpoint_status': checkpoint_status,
            'complete': len(checkpoint_pages) == total_pages and checkpoint_status == 'completed'
        }

    # Check vision selection
    vision_checkpoint_file = book_dir / 'ocr' / 'psm_selection' / '.checkpoint'
    vision_complete = False
    vision_pages = 0

    if vision_checkpoint_file.exists():
        try:
            vision_data = json.loads(vision_checkpoint_file.read_text())
            vision_pages = len(vision_data.get('page_metrics', {}))
            vision_complete = vision_data.get('status') == 'completed'
        except:
            pass

    # Determine overall state
    all_psms_complete = all(state['complete'] for state in psm_states.values())
    all_complete = all_psms_complete and vision_complete

    # Update main checkpoint
    main_checkpoint = CheckpointManager(
        scan_id=scan_id,
        stage='ocr',
        storage_root=storage_root
    )

    with main_checkpoint._lock:
        # Update total_pages
        main_checkpoint._state['total_pages'] = total_pages

        # Update status
        if all_complete:
            main_checkpoint._state['status'] = 'completed'
        elif any(state['checkpoint_pages'] > 0 for state in psm_states.values()) or vision_pages > 0:
            main_checkpoint._state['status'] = 'in_progress'
        else:
            main_checkpoint._state['status'] = 'not_started'

        # Save
        main_checkpoint._save_checkpoint()

    return {
        'total_pages': total_pages,
        'psm_states': psm_states,
        'vision_pages': vision_pages,
        'vision_complete': vision_complete,
        'all_psms_complete': all_psms_complete,
        'all_complete': all_complete,
        'main_status': main_checkpoint._state['status']
    }


def main():
    """Sync all books in library."""
    print("🔄 Syncing OCR checkpoints across library\n")

    storage_root = Config.book_storage_root
    library = Library(storage_root)

    all_books = library.list_books()
    print(f"Found {len(all_books)} books\n")

    synced_count = 0
    error_count = 0

    for idx, book in enumerate(all_books, 1):
        scan_id = book['scan_id']
        print(f"[{idx}/{len(all_books)}] {scan_id}")

        try:
            result = sync_book(scan_id, storage_root)

            if 'error' in result:
                print(f"  ⏭️  Skipped: {result['error']}")
                error_count += 1
                continue

            # Print status
            psm_summary = []
            for psm, state in result['psm_states'].items():
                status_icon = '✅' if state['complete'] else ('⏳' if state['checkpoint_pages'] > 0 else '○')
                psm_summary.append(f"PSM{psm}:{status_icon}{state['checkpoint_pages']}/{result['total_pages']}")

            vision_icon = '✅' if result['vision_complete'] else ('⏳' if result['vision_pages'] > 0 else '○')
            vision_summary = f"Vision:{vision_icon}{result['vision_pages']}/{result['total_pages']}"

            print(f"  {' '.join(psm_summary)} {vision_summary}")
            print(f"  Main checkpoint: {result['main_status']}")

            synced_count += 1

        except Exception as e:
            print(f"  ❌ Error: {e}")
            error_count += 1
            continue

    print(f"\n✅ Sync complete")
    print(f"   Synced: {synced_count} books")
    print(f"   Errors: {error_count} books")


if __name__ == '__main__':
    main()
