"""
Library-level tracking and management for book collection.

The library.json file at BOOK_STORAGE_ROOT is the single source of truth
for all books and their associated scans.
"""

import json
import os
import copy
import threading
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from infra.config import Config


class LibraryIndex:
    """Manages the library catalog (library.json)."""

    def __init__(self, storage_root: Path = None):
        """
        Initialize library index.

        Args:
            storage_root: Path to book storage root (defaults to Config.BOOK_STORAGE_ROOT)
        """
        self.storage_root = storage_root or Config.BOOK_STORAGE_ROOT
        self.library_file = self.storage_root / "library.json"

        # Thread-safe lock for atomic operations
        self._lock = threading.Lock()

        # Ensure storage root exists
        self.storage_root.mkdir(parents=True, exist_ok=True)

        # Load or create library
        file_existed = self.library_file.exists()
        self.data = self._load()

        # Save if newly created
        if not file_existed:
            self.save()

    def _load(self) -> Dict[str, Any]:
        """Load library.json or create default structure."""
        if self.library_file.exists():
            with open(self.library_file, 'r') as f:
                return json.load(f)
        else:
            # Create default structure
            return {
                "version": "1.0",
                "last_updated": datetime.now().isoformat(),
                "books": {},
                "watch_dirs": [],
                "stats": {
                    "total_books": 0,
                    "total_scans": 0,
                    "total_pages": 0,
                    "total_cost_usd": 0.0
                }
            }

    def save(self):
        """
        Save library.json to disk with atomic write.

        Uses temp file + atomic rename pattern for crash safety.
        Must be called with lock held for thread safety.
        """
        self.data["last_updated"] = datetime.now().isoformat()
        self._update_stats()

        temp_file = self.library_file.with_suffix('.json.tmp')

        try:
            # Write to temp file
            with open(temp_file, 'w') as f:
                json.dump(self.data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Force OS to write

            # Validate temp file is valid JSON before replacing
            with open(temp_file, 'r') as f:
                json.load(f)  # Throws if corrupt

            # Atomic rename
            temp_file.replace(self.library_file)

        except Exception as e:
            # Clean up temp file on failure
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception as cleanup_error:
                    # Log but don't fail on cleanup
                    logging.warning(f"Could not remove temp file {temp_file}: {cleanup_error}")
            raise RuntimeError(f"Failed to save library: {e}") from e

    def _update_stats(self):
        """Recalculate library-wide statistics."""
        total_books = len(self.data["books"])
        total_scans = sum(len(book["scans"]) for book in self.data["books"].values())
        total_pages = 0
        total_cost = 0.0

        for book in self.data["books"].values():
            for scan in book["scans"]:
                total_pages += scan.get("pages", 0)
                total_cost += scan.get("cost_usd", 0.0)

        self.data["stats"] = {
            "total_books": total_books,
            "total_scans": total_scans,
            "total_pages": total_pages,
            "total_cost_usd": round(total_cost, 2)
        }

    def add_book(
        self,
        title: str,
        author: str,
        scan_id: str,
        isbn: str = None,
        year: int = None,
        publisher: str = None,
        tags: List[str] = None,
        source_file: str = None,
        notes: str = None
    ) -> str:
        """
        Add a new book to the library.

        Args:
            title: Book title
            author: Author name
            scan_id: Random scan identifier (folder name)
            isbn: ISBN-10 or ISBN-13
            year: Publication year
            publisher: Publisher name
            tags: List of tags for categorization
            source_file: Original PDF filename
            notes: Optional notes about this scan

        Returns:
            Book slug (key in library.json)
        """
        # Generate book slug from title
        book_slug = self._generate_book_slug(title)

        # Check scan_id is unique across all books
        for book in self.data["books"].values():
            for scan in book["scans"]:
                if scan["scan_id"] == scan_id:
                    raise ValueError(f"Scan ID '{scan_id}' already exists in library")

        # If book doesn't exist, create it
        if book_slug not in self.data["books"]:
            self.data["books"][book_slug] = {
                "title": title,
                "author": author,
                "isbn": isbn,
                "year": year,
                "publisher": publisher,
                "tags": tags or [],
                "scans": []
            }

        # Add scan entry
        scan_entry = {
            "scan_id": scan_id,
            "date_added": datetime.now().isoformat(),
            "source_file": source_file,
            "models": {},
            "pages": 0,
            "cost_usd": 0.0,
            "status": "registered",
            "notes": notes
        }

        self.data["books"][book_slug]["scans"].append(scan_entry)
        self.save()

        return book_slug

    def register_scan(
        self,
        book_slug: str,
        scan_id: str,
        source_file: str = None,
        notes: str = None
    ):
        """
        Register a new scan for an existing book.

        Args:
            book_slug: Book identifier in library
            scan_id: Random scan identifier
            source_file: Original PDF filename
            notes: Optional notes
        """
        if book_slug not in self.data["books"]:
            raise ValueError(f"Book {book_slug} not found in library")

        scan_entry = {
            "scan_id": scan_id,
            "date_added": datetime.now().isoformat(),
            "source_file": source_file,
            "models": {},
            "pages": 0,
            "cost_usd": 0.0,
            "status": "registered",
            "notes": notes
        }

        self.data["books"][book_slug]["scans"].append(scan_entry)
        self.save()

    def update_scan_metadata(
        self,
        scan_id: str,
        metadata: Dict[str, Any]
    ):
        """
        Update metadata for a scan (called by pipeline).

        Args:
            scan_id: Scan identifier
            metadata: Dictionary with updates (pages, cost_usd, models, status, etc.)
        """
        # Find the scan
        book_slug, scan_idx = self._find_scan(scan_id)
        if book_slug is None:
            raise ValueError(f"Scan {scan_id} not found in library")

        # Update fields
        scan = self.data["books"][book_slug]["scans"][scan_idx]
        for key, value in metadata.items():
            scan[key] = value

        self.save()

    def sync_scan_from_metadata(self, scan_id: str):
        """
        Sync scan data from its metadata.json to library.json.

        Reads cost and model information from the scan's metadata.json
        processing_history and updates library.json accordingly.

        Args:
            scan_id: Scan identifier
        """
        from infra.storage.metadata import get_scan_total_cost, get_scan_models

        scan_dir = self.storage_root / scan_id
        if not scan_dir.exists():
            raise ValueError(f"Scan directory not found: {scan_dir}")

        # Get cost and models from scan metadata
        total_cost = get_scan_total_cost(scan_dir)
        models = get_scan_models(scan_dir)

        # Get page count from structured metadata if available
        structured_meta_file = scan_dir / "structured" / "metadata.json"
        pages = 0
        if structured_meta_file.exists():
            with open(structured_meta_file, 'r') as f:
                structured_meta = json.load(f)
                pages = structured_meta.get('book_info', {}).get('total_pages', 0)

        # Update library
        self.update_scan_metadata(scan_id, {
            'cost_usd': total_cost,
            'models': models,
            'pages': pages,
            'status': 'complete' if models else 'registered'
        })

    def get_scan_info(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """
        Get full information for a scan.

        Args:
            scan_id: Scan identifier

        Returns:
            Dict with book info + scan info, or None if not found
        """
        book_slug, scan_idx = self._find_scan(scan_id)
        if book_slug is None:
            return None

        book = self.data["books"][book_slug]
        scan = book["scans"][scan_idx]

        return {
            "book_slug": book_slug,
            "title": book["title"],
            "author": book["author"],
            "isbn": book.get("isbn"),
            "scan": scan
        }

    def get_book_scans(self, book_slug: str) -> List[Dict[str, Any]]:
        """Get all scans for a book."""
        if book_slug not in self.data["books"]:
            return []
        return self.data["books"][book_slug]["scans"]

    def list_all_books(self) -> List[Dict[str, Any]]:
        """Get list of all books with basic info."""
        books = []
        for slug, book in self.data["books"].items():
            books.append({
                "slug": slug,
                "title": book["title"],
                "author": book["author"],
                "scan_count": len(book["scans"]),
                "tags": book.get("tags", [])
            })
        return sorted(books, key=lambda x: x["title"])

    def list_all_scans(self) -> List[Dict[str, Any]]:
        """Get list of all scans across all books."""
        scans = []
        for book_slug, book in self.data["books"].items():
            for scan in book["scans"]:
                scans.append({
                    "scan_id": scan["scan_id"],
                    "book_slug": book_slug,
                    "title": book["title"],
                    "author": book["author"],
                    "status": scan["status"],
                    "date_added": scan["date_added"]
                })
        return sorted(scans, key=lambda x: x["date_added"], reverse=True)

    def get_stats(self) -> Dict[str, Any]:
        """Get library-wide statistics."""
        return self.data["stats"]

    def _generate_book_slug(self, title: str) -> str:
        """
        Generate a URL-safe slug from book title.

        Args:
            title: Book title

        Returns:
            Lowercase slug with hyphens
        """
        import re
        # Lowercase, replace spaces/punctuation with hyphens
        slug = title.lower()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug.strip('-')

    def _find_scan(self, scan_id: str) -> tuple[Optional[str], Optional[int]]:
        """
        Find book_slug and scan index for a given scan_id.

        Returns:
            (book_slug, scan_index) or (None, None) if not found
        """
        for book_slug, book in self.data["books"].items():
            for idx, scan in enumerate(book["scans"]):
                if scan["scan_id"] == scan_id:
                    return book_slug, idx
        return None, None

    @contextmanager
    def update_scan(self, scan_id: str):
        """
        Atomic context manager for updating scan metadata.

        Provides all-or-nothing updates: changes are committed on success,
        rolled back on exception. Thread-safe.

        Usage:
            with library.update_scan(scan_id) as scan:
                scan['status'] = 'corrected'
                scan['cost_usd'] = 5.50
                scan['pages'] = 447
                # Commit happens automatically on success
                # Rollback on exception

        Args:
            scan_id: Scan identifier

        Yields:
            Mutable scan dictionary

        Raises:
            ValueError: If scan not found
            RuntimeError: If save fails
        """
        with self._lock:
            # Find the scan
            book_slug, scan_idx = self._find_scan(scan_id)
            if book_slug is None:
                raise ValueError(f"Scan {scan_id} not found in library")

            # Get reference to scan
            scan = self.data["books"][book_slug]["scans"][scan_idx]

            # Deep copy for rollback
            original_scan = copy.deepcopy(scan)
            original_data = copy.deepcopy(self.data)

            try:
                # Yield mutable scan dict
                yield scan

                # Commit: save to disk
                self.save()

            except Exception as e:
                # Rollback: restore original state
                self.data = original_data
                raise  # Re-raise the exception

    def validate_library(self) -> Dict[str, Any]:
        """
        Validate library consistency with disk state.

        Checks:
        1. All scans in library have directories on disk
        2. All scan directories have entries in library
        3. Costs match between library and scan metadata.json
        4. Models match between library and scan metadata.json

        Returns:
            Dictionary with validation results:
            {
                "valid": bool,
                "issues": [
                    {
                        "type": "missing_scan_dir" | "orphaned_scan_dir" | "cost_mismatch" | "model_mismatch",
                        "scan_id": str,
                        "details": str,
                        "expected": Any,
                        "actual": Any
                    },
                    ...
                ],
                "stats": {
                    "total_scans_in_library": int,
                    "total_scan_dirs_on_disk": int,
                    "missing_scan_dirs": int,
                    "orphaned_scan_dirs": int,
                    "cost_mismatches": int,
                    "model_mismatches": int
                }
            }
        """
        from infra.storage.metadata import get_scan_total_cost, get_scan_models

        issues = []
        stats = {
            "total_scans_in_library": 0,
            "total_scan_dirs_on_disk": 0,
            "missing_scan_dirs": 0,
            "orphaned_scan_dirs": 0,
            "cost_mismatches": 0,
            "model_mismatches": 0
        }

        # Get all scan IDs from library
        library_scan_ids = set()
        for book in self.data["books"].values():
            for scan in book["scans"]:
                library_scan_ids.add(scan["scan_id"])

        stats["total_scans_in_library"] = len(library_scan_ids)

        # Get all scan directories from disk
        disk_scan_ids = set()
        for item in self.storage_root.iterdir():
            if item.is_dir() and item.name != "library.json":
                # Check if it looks like a scan directory (has source/ or ocr/ etc.)
                if (item / "source").exists() or (item / "ocr").exists() or (item / "metadata.json").exists():
                    disk_scan_ids.add(item.name)

        stats["total_scan_dirs_on_disk"] = len(disk_scan_ids)

        # Check 1: Scans in library but not on disk
        missing_dirs = library_scan_ids - disk_scan_ids
        for scan_id in missing_dirs:
            issues.append({
                "type": "missing_scan_dir",
                "scan_id": scan_id,
                "details": f"Scan {scan_id} is in library but directory not found on disk",
                "expected": f"{self.storage_root / scan_id}",
                "actual": None
            })
        stats["missing_scan_dirs"] = len(missing_dirs)

        # Check 2: Scan directories on disk but not in library
        orphaned_dirs = disk_scan_ids - library_scan_ids
        for scan_id in orphaned_dirs:
            issues.append({
                "type": "orphaned_scan_dir",
                "scan_id": scan_id,
                "details": f"Scan directory {scan_id} exists on disk but not in library",
                "expected": None,
                "actual": f"{self.storage_root / scan_id}"
            })
        stats["orphaned_scan_dirs"] = len(orphaned_dirs)

        # Check 3 & 4: For scans in both, validate costs and models
        common_scans = library_scan_ids & disk_scan_ids
        for scan_id in common_scans:
            scan_dir = self.storage_root / scan_id
            scan_info = self.get_scan_info(scan_id)

            if not scan_info:
                continue

            # Get actual costs and models from disk
            try:
                actual_cost = get_scan_total_cost(scan_dir)
                actual_models = get_scan_models(scan_dir)

                # Check cost mismatch
                library_cost = scan_info["scan"].get("cost_usd", 0.0)
                if abs(library_cost - actual_cost) > 0.01:  # Allow 1 cent rounding
                    issues.append({
                        "type": "cost_mismatch",
                        "scan_id": scan_id,
                        "details": f"Cost mismatch for {scan_id}",
                        "expected": actual_cost,
                        "actual": library_cost
                    })
                    stats["cost_mismatches"] += 1

                # Check model mismatch
                library_models = scan_info["scan"].get("models", {})
                if actual_models != library_models:
                    # Find specific differences
                    all_stages = set(actual_models.keys()) | set(library_models.keys())
                    for stage in all_stages:
                        actual = actual_models.get(stage)
                        library = library_models.get(stage)
                        if actual != library:
                            issues.append({
                                "type": "model_mismatch",
                                "scan_id": scan_id,
                                "details": f"Model mismatch for {scan_id} stage '{stage}'",
                                "expected": actual,
                                "actual": library
                            })
                            stats["model_mismatches"] += 1

            except Exception as e:
                # Error reading metadata - report as issue
                issues.append({
                    "type": "validation_error",
                    "scan_id": scan_id,
                    "details": f"Error validating {scan_id}: {str(e)}",
                    "expected": None,
                    "actual": None
                })

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "stats": stats
        }

    def auto_fix_validation_issues(self, validation_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Automatically fix validation issues where possible.

        Fixes:
        - Orphaned scan directories: Add to library with metadata from disk
        - Cost mismatches: Sync from disk to library
        - Model mismatches: Sync from disk to library

        Does NOT fix:
        - Missing scan directories (requires manual recovery)

        Args:
            validation_result: Result from validate_library()

        Returns:
            Dictionary with fix results:
            {
                "fixed_count": int,
                "unfixable_count": int,
                "fixed_issues": [issue_type, ...],
                "unfixable_issues": [issue_type, ...]
            }
        """
        fixed = []
        unfixable = []

        for issue in validation_result["issues"]:
            issue_type = issue["type"]
            scan_id = issue["scan_id"]

            try:
                if issue_type == "cost_mismatch":
                    # Sync cost from disk
                    self.sync_scan_from_metadata(scan_id)
                    fixed.append(issue_type)

                elif issue_type == "model_mismatch":
                    # Sync models from disk
                    self.sync_scan_from_metadata(scan_id)
                    fixed.append(issue_type)

                elif issue_type == "orphaned_scan_dir":
                    # Try to add to library from disk metadata
                    scan_dir = self.storage_root / scan_id
                    metadata_file = scan_dir / "metadata.json"

                    if metadata_file.exists():
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)

                        title = metadata.get("title", scan_id)
                        author = metadata.get("author", "Unknown")

                        # Add to library
                        self.add_book(
                            title=title,
                            author=author,
                            scan_id=scan_id,
                            notes="Auto-recovered from orphaned directory"
                        )

                        # Sync metadata
                        self.sync_scan_from_metadata(scan_id)
                        fixed.append(issue_type)
                    else:
                        unfixable.append(issue_type)

                elif issue_type == "missing_scan_dir":
                    # Cannot auto-fix - directory is gone
                    unfixable.append(issue_type)

                else:
                    unfixable.append(issue_type)

            except Exception as e:
                logging.warning(f"Could not fix {issue_type} for {scan_id}: {e}")
                unfixable.append(issue_type)

        return {
            "fixed_count": len(fixed),
            "unfixable_count": len(unfixable),
            "fixed_issues": fixed,
            "unfixable_issues": unfixable
        }

    def delete_scan(
        self,
        scan_id: str,
        delete_files: bool = True,
        remove_empty_book: bool = True
    ) -> Dict[str, Any]:
        """
        Delete a scan from the library and optionally remove its files.

        Args:
            scan_id: Scan identifier to delete
            delete_files: If True, delete the scan directory from disk (default: True)
            remove_empty_book: If True, remove book entry if it has no more scans (default: True)

        Returns:
            Dictionary with deletion results:
            {
                "scan_id": str,
                "book_slug": str,
                "deleted_from_library": bool,
                "files_deleted": bool,
                "book_removed": bool,
                "scan_dir": str or None
            }

        Raises:
            ValueError: If scan not found
            RuntimeError: If deletion fails
        """
        import shutil

        with self._lock:
            # Find the scan
            book_slug, scan_idx = self._find_scan(scan_id)
            if book_slug is None:
                raise ValueError(f"Scan {scan_id} not found in library")

            # Get scan info before deletion
            scan_dir = self.storage_root / scan_id

            # Remove from library
            book = self.data["books"][book_slug]
            book["scans"].pop(scan_idx)

            # Check if book now has no scans
            book_removed = False
            if remove_empty_book and len(book["scans"]) == 0:
                del self.data["books"][book_slug]
                book_removed = True

            # Save library changes
            self.save()

            # Delete files if requested
            files_deleted = False
            if delete_files and scan_dir.exists():
                try:
                    shutil.rmtree(scan_dir)
                    files_deleted = True
                except Exception as e:
                    raise RuntimeError(f"Failed to delete scan directory {scan_dir}: {e}") from e

            return {
                "scan_id": scan_id,
                "book_slug": book_slug,
                "deleted_from_library": True,
                "files_deleted": files_deleted,
                "book_removed": book_removed,
                "scan_dir": str(scan_dir) if scan_dir.exists() or files_deleted else None
            }
