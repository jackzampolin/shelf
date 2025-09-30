"""
Library-level tracking and management for book collection.

The library.json file at BOOK_STORAGE_ROOT is the single source of truth
for all books and their associated scans.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from config import Config
from tools.names import ensure_unique_scan_id


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
        self.data = self._load()

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
        """Save library.json to disk."""
        self.data["last_updated"] = datetime.now().isoformat()
        self._update_stats()

        with open(self.library_file, 'w') as f:
            json.dump(self.data, f, indent=2)

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

    def migrate_existing_folder(
        self,
        old_folder_name: str,
        title: str = None,
        author: str = None
    ) -> str:
        """
        Migrate an existing folder to the new naming system.

        Args:
            old_folder_name: Current folder name (e.g., "The-Accidental-President")
            title: Book title (if not provided, will attempt to read from metadata)
            author: Book author (if not provided, will attempt to read from metadata)

        Returns:
            New scan_id
        """
        old_path = self.storage_root / old_folder_name

        if not old_path.exists():
            raise ValueError(f"Folder {old_folder_name} not found")

        # Try to read metadata from folder
        metadata_file = old_path / "metadata.json"
        if metadata_file.exists() and (title is None or author is None):
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
                title = title or metadata.get("title", old_folder_name)
                author = author or metadata.get("author", "Unknown")

        # Generate unique scan ID
        existing_scan_ids = [
            scan["scan_id"]
            for book in self.data["books"].values()
            for scan in book["scans"]
        ]
        scan_id = ensure_unique_scan_id(existing_scan_ids)

        # Rename folder
        new_path = self.storage_root / scan_id
        old_path.rename(new_path)

        # Add to library
        self.add_book(
            title=title,
            author=author,
            scan_id=scan_id,
            notes=f"Migrated from {old_folder_name}"
        )

        return scan_id

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
