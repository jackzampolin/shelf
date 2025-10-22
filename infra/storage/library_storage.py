"""
Library-level tracking and management for book collection.

FILESYSTEM-BASED: No library.json - all data derived from scanning directories.

Coordinates multiple BookStorage instances and provides library-wide
operations like listing books, searching, and aggregating statistics.

Single source of truth:
- Book directories in BOOK_STORAGE_ROOT (existence)
- metadata.json per book (title, author, year, etc.)
- Checkpoint files per stage (pipeline status, costs)
"""

import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from infra.config import Config


class LibraryStorage:
    """
    Manages library operations by scanning filesystem.

    No library.json - derives everything from:
    1. Book directories in storage_root
    2. metadata.json files per book
    3. Checkpoint files per stage

    Provides library-wide operations:
    - List all books (scan directories)
    - Get book info (read metadata.json)
    - Get pipeline status (read checkpoint files)
    - Calculate statistics (aggregate from checkpoints)
    - BookStorage instance coordination
    """

    def __init__(self, storage_root: Path = None):
        """
        Initialize library storage.

        Args:
            storage_root: Path to book storage root (defaults to Config.BOOK_STORAGE_ROOT)
        """
        self.storage_root = storage_root or Config.BOOK_STORAGE_ROOT

        # Cache for BookStorage instances (lazy loading)
        self._book_storage_cache: Dict[str, Any] = {}

        # Ensure storage root exists
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def _scan_book_directories(self) -> List[str]:
        """
        Scan storage root for book directories.

        Returns:
            List of scan_ids (directory names that look like books)
        """
        scan_ids = []

        if not self.storage_root.exists():
            return scan_ids

        for item in self.storage_root.iterdir():
            if not item.is_dir():
                continue

            # Skip hidden directories
            if item.name.startswith('.'):
                continue

            # Check if it looks like a book directory
            # (has metadata.json or source/ directory)
            metadata_file = item / "metadata.json"
            source_dir = item / "source"

            if metadata_file.exists() or source_dir.exists():
                scan_ids.append(item.name)

        return sorted(scan_ids)

    def _read_metadata(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """
        Read metadata.json for a book.

        Args:
            scan_id: Book scan ID

        Returns:
            Metadata dict or None if not found
        """
        metadata_file = self.storage_root / scan_id / "metadata.json"

        if not metadata_file.exists():
            return None

        try:
            with open(metadata_file, 'r') as f:
                return json.load(f)
        except Exception:
            return None

    def _get_pipeline_status(self, scan_id: str) -> Dict[str, str]:
        """
        Get pipeline status for all stages by reading checkpoints.

        Args:
            scan_id: Book scan ID

        Returns:
            Dict mapping stage names to status ("not_started", "in_progress", "completed", "failed")
        """
        from infra.storage.book_storage import BookStorage

        storage = self.get_book_storage(scan_id)
        status = {}

        for stage_name in ['ocr', 'corrected', 'labels', 'merged']:
            stage_storage = storage.stage(stage_name)
            checkpoint = stage_storage.checkpoint
            checkpoint_status = checkpoint.get_status()
            status[stage_name] = checkpoint_status.get('status', 'not_started')

        return status

    def _calculate_book_cost(self, scan_id: str) -> float:
        """
        Calculate total cost for a book from all stage checkpoints.

        Args:
            scan_id: Book scan ID

        Returns:
            Total cost in USD
        """
        from infra.storage.book_storage import BookStorage

        storage = self.get_book_storage(scan_id)
        total_cost = 0.0

        for stage_name in ['ocr', 'corrected', 'labels', 'merged']:
            stage_storage = storage.stage(stage_name)
            checkpoint = stage_storage.checkpoint
            checkpoint_status = checkpoint.get_status()

            # Get cost from checkpoint metadata
            metadata = checkpoint_status.get('metadata', {})
            stage_cost = metadata.get('total_cost_usd', 0.0)
            total_cost += stage_cost

        return total_cost

    def list_all_books(self) -> List[Dict[str, Any]]:
        """
        Get list of all books by scanning directories.

        Returns:
            List of book info dicts with title, author, scan_id, etc.
        """
        books = []
        scan_ids = self._scan_book_directories()

        for scan_id in scan_ids:
            metadata = self._read_metadata(scan_id)

            if not metadata:
                # Book exists but no metadata yet
                books.append({
                    "scan_id": scan_id,
                    "title": scan_id,  # Use scan_id as fallback
                    "author": "Unknown",
                    "year": None,
                    "pages": 0,
                    "status": "incomplete"
                })
            else:
                books.append({
                    "scan_id": scan_id,
                    "title": metadata.get('title', scan_id),
                    "author": metadata.get('author', 'Unknown'),
                    "year": metadata.get('year'),
                    "publisher": metadata.get('publisher'),
                    "pages": metadata.get('total_pages', 0),
                    "date_added": metadata.get('scan_date'),
                })

        return books

    def list_all_scans(self) -> List[Dict[str, Any]]:
        """
        Get list of all scans (same as books for now - one scan per book).

        Returns:
            List of scan info dicts
        """
        return self.list_all_books()

    def get_scan_info(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """
        Get full information for a scan.

        Args:
            scan_id: Scan identifier

        Returns:
            Dict with book info + scan info, or None if not found
        """
        book_dir = self.storage_root / scan_id

        if not book_dir.exists():
            return None

        metadata = self._read_metadata(scan_id)

        if not metadata:
            return {
                "scan_id": scan_id,
                "title": scan_id,
                "author": "Unknown",
                "scan": {
                    "scan_id": scan_id,
                    "status": "incomplete"
                }
            }

        # Calculate cost from checkpoints
        cost = self._calculate_book_cost(scan_id)

        return {
            "scan_id": scan_id,
            "title": metadata.get('title', scan_id),
            "author": metadata.get('author', 'Unknown'),
            "year": metadata.get('year'),
            "publisher": metadata.get('publisher'),
            "isbn": metadata.get('isbn'),
            "scan": {
                "scan_id": scan_id,
                "date_added": metadata.get('scan_date'),
                "pages": metadata.get('total_pages', 0),
                "cost_usd": cost,
                "status": "processing"
            }
        }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get library-wide statistics by scanning all books.

        Returns:
            Dict with totals: books, scans, pages, cost
        """
        scan_ids = self._scan_book_directories()

        total_pages = 0
        total_cost = 0.0

        for scan_id in scan_ids:
            metadata = self._read_metadata(scan_id)
            if metadata:
                total_pages += metadata.get('total_pages', 0)

            # Get cost from checkpoints
            total_cost += self._calculate_book_cost(scan_id)

        return {
            "total_books": len(scan_ids),
            "total_scans": len(scan_ids),
            "total_pages": total_pages,
            "total_cost_usd": round(total_cost, 2)
        }

    def delete_scan(
        self,
        scan_id: str,
        delete_files: bool = True,
        remove_empty_book: bool = True
    ) -> Dict[str, Any]:
        """
        Delete a scan from the library.

        Args:
            scan_id: Scan identifier to delete
            delete_files: If True, delete the scan directory from disk (default: True)
            remove_empty_book: Ignored (kept for API compatibility)

        Returns:
            Dictionary with deletion results

        Raises:
            ValueError: If scan not found
            RuntimeError: If deletion fails
        """
        book_dir = self.storage_root / scan_id

        if not book_dir.exists():
            raise ValueError(f"Scan {scan_id} not found in library")

        # Delete files if requested
        files_deleted = False
        if delete_files:
            try:
                shutil.rmtree(book_dir)
                files_deleted = True
            except Exception as e:
                raise RuntimeError(f"Failed to delete scan directory {book_dir}: {e}") from e

        return {
            "scan_id": scan_id,
            "deleted_from_library": True,
            "files_deleted": files_deleted,
            "book_removed": files_deleted,  # Same as files_deleted now
            "scan_dir": str(book_dir) if files_deleted else None
        }

    def get_book_storage(self, scan_id: str):
        """
        Get a BookStorage instance for a scan.

        Uses lazy loading with caching for performance.

        Args:
            scan_id: Scan identifier

        Returns:
            BookStorage instance for the scan

        Raises:
            ValueError: If scan not found in library
        """
        from infra.storage.book_storage import BookStorage

        book_dir = self.storage_root / scan_id

        if not book_dir.exists():
            raise ValueError(f"Scan {scan_id} not found in library")

        # Return cached instance if available
        if scan_id in self._book_storage_cache:
            return self._book_storage_cache[scan_id]

        # Create new instance and cache it
        storage = BookStorage(scan_id, storage_root=self.storage_root)
        self._book_storage_cache[scan_id] = storage

        return storage
