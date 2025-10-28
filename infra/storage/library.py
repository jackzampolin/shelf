"""
Library management class - single source of truth for book operations.

Provides a unified interface for all library operations that maintains
consistency between filesystem state and operational metadata (shuffles).

Philosophy:
- Books exist on filesystem (source of truth for what exists)
- Operational state lives in .library.json (shuffle orders, etc.)
- Library class coordinates both to maintain consistency

Usage:
    from infra.storage.library import Library

    library = Library()

    # Add book (creates directory + updates shuffles)
    scan_ids = library.add_books(['path/to/book.pdf'])

    # Delete book (removes directory + updates shuffles)
    library.delete_book('scan-id', confirm=True)

    # List books (delegates to LibraryStorage)
    books = library.list_books()

    # Shuffle management (coordinates with metadata)
    library.create_shuffle('labels', reshuffle=False)
    order = library.get_shuffle('labels')
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
import random

from infra.config import Config
from infra.storage.library_storage import LibraryStorage
from infra.storage.library_metadata import LibraryMetadata
from infra.storage.book_storage import BookStorage


class Library:
    """
    Unified library management interface.

    Coordinates LibraryStorage (filesystem) and LibraryMetadata (operational state)
    to provide a consistent, high-level API for all library operations.

    Ensures:
    - Shuffle state stays in sync when books are added/deleted
    - Defensive loading (filters out missing books from shuffles)
    - Single entry point for all library operations
    """

    def __init__(self, storage_root: Optional[Path] = None):
        """
        Initialize library.

        Args:
            storage_root: Path to library root (defaults to Config.book_storage_root)
        """
        self.storage_root = storage_root or Config.book_storage_root

        # Coordinate these two subsystems
        self._storage = LibraryStorage(storage_root=self.storage_root)
        self._metadata = LibraryMetadata(storage_root=self.storage_root)

    # ===== Book Operations =====

    def add_books(self, pdf_paths: List[Path], run_ocr: bool = False) -> Dict[str, Any]:
        """
        Add books to library and update all shuffle orders.

        Args:
            pdf_paths: List of PDF file paths to add
            run_ocr: Whether to run OCR immediately

        Returns:
            Dict with keys: books_added (int), scan_ids (List[str])
        """
        from infra.utils.ingest import add_books_to_library

        # Add books to filesystem
        result = add_books_to_library(
            pdf_paths=pdf_paths,
            storage_root=self.storage_root,
            run_ocr=run_ocr
        )

        # Update all existing shuffles (append new books to end)
        new_scan_ids = result['scan_ids']
        if new_scan_ids:
            self._add_books_to_shuffles(new_scan_ids)

        return result

    def delete_book(
        self,
        scan_id: str,
        delete_files: bool = True,
        remove_empty_book: bool = True
    ) -> Dict[str, Any]:
        """
        Delete book from library and update all shuffle orders.

        Args:
            scan_id: Book scan ID to delete
            delete_files: Whether to delete files (vs just removing entry)
            remove_empty_book: Whether to remove empty book directory

        Returns:
            Dict with keys: scan_id (str), files_deleted (bool), scan_dir (Path)
        """
        # Delete from filesystem
        result = self._storage.delete_scan(
            scan_id=scan_id,
            delete_files=delete_files,
            remove_empty_book=remove_empty_book
        )

        # Remove from all shuffles
        self._remove_book_from_shuffles(scan_id)

        return result

    def get_book_storage(self, scan_id: str) -> BookStorage:
        """Get BookStorage instance for a specific book."""
        return self._storage.get_book_storage(scan_id)

    def get_book_info(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """Get book information (metadata + pipeline status)."""
        return self._storage.get_scan_info(scan_id)

    def list_books(self) -> List[Dict[str, Any]]:
        """List all books in library."""
        return self._storage.list_all_books()

    # ===== Shuffle Operations =====

    def get_shuffle(self, defensive: bool = True) -> Optional[List[str]]:
        """
        Get global shuffle order.

        Args:
            defensive: Filter out books that don't exist on filesystem

        Returns:
            List of scan_ids in shuffle order, or None if no shuffle exists
        """
        shuffle = self._metadata.get_shuffle()

        if shuffle is None:
            return None

        if not defensive:
            return shuffle

        # Defensive: Filter out books that no longer exist
        existing_scan_ids = {book['scan_id'] for book in self.list_books()}
        valid_shuffle = [sid for sid in shuffle if sid in existing_scan_ids]

        # If shuffle changed, save the cleaned version
        if len(valid_shuffle) != len(shuffle):
            self._metadata.set_shuffle(valid_shuffle)

        return valid_shuffle

    def create_shuffle(
        self,
        reshuffle: bool = False,
        books: Optional[List[str]] = None
    ) -> List[str]:
        """
        Create or get global shuffle order.

        Args:
            reshuffle: Force creation of new random order
            books: Optional list of scan_ids to shuffle (defaults to all books)

        Returns:
            List of scan_ids in shuffle order
        """
        # Check for existing shuffle
        existing_shuffle = self.get_shuffle(defensive=True)

        if not reshuffle and existing_shuffle:
            # Use existing shuffle, but add any new books
            if books is None:
                books = [book['scan_id'] for book in self.list_books()]

            existing_set = set(existing_shuffle)
            new_books = [sid for sid in books if sid not in existing_set]

            if new_books:
                # Add new books to end (preserves existing order)
                random.shuffle(new_books)
                updated_shuffle = existing_shuffle + new_books
                self._metadata.set_shuffle(updated_shuffle)
                return updated_shuffle

            return existing_shuffle

        # Create new shuffle
        if books is None:
            books = [book['scan_id'] for book in self.list_books()]

        shuffled = books.copy()
        random.shuffle(shuffled)
        self._metadata.set_shuffle(shuffled)

        return shuffled

    def clear_shuffle(self):
        """Clear global shuffle order."""
        self._metadata.clear_shuffle()

    def has_shuffle(self) -> bool:
        """Check if global shuffle exists."""
        return self._metadata.has_shuffle()

    def get_shuffle_info(self) -> Optional[Dict[str, Any]]:
        """Get shuffle metadata (created_at, count)."""
        return self._metadata.get_shuffle_info()

    # ===== Private Helpers =====

    def _add_books_to_shuffles(self, scan_ids: List[str]):
        """Add books to global shuffle (appends to end)."""
        current_shuffle = self._metadata.get_shuffle()

        if current_shuffle:
            # Append new books to end (preserves order for in-progress operations)
            random.shuffle(scan_ids)  # Randomize new books relative to each other
            updated_shuffle = current_shuffle + scan_ids
            self._metadata.set_shuffle(updated_shuffle)

    def _remove_book_from_shuffles(self, scan_id: str):
        """Remove book from global shuffle."""
        current_shuffle = self._metadata.get_shuffle()

        if current_shuffle and scan_id in current_shuffle:
            updated_shuffle = [sid for sid in current_shuffle if sid != scan_id]
            self._metadata.set_shuffle(updated_shuffle)

    # ===== Delegation to LibraryStorage =====
    # These methods delegate to LibraryStorage for backward compatibility

    def get_stats(self) -> Dict[str, Any]:
        """Get library statistics."""
        return self._storage.get_stats()

    def list_all_scans(self) -> List[Dict[str, Any]]:
        """List all scans (alias for list_books for backward compatibility)."""
        return self._storage.list_all_scans()

    def get_scan_info(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """Get scan information (alias for get_book_info for backward compatibility)."""
        return self._storage.get_scan_info(scan_id)
