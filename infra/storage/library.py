"""High-level Library coordinator (combines LibraryStorage + LibraryMetadata)"""

from pathlib import Path
from typing import Optional, List, Dict, Any
import random

from infra.config import Config
from infra.storage.library_storage import LibraryStorage
from infra.storage.library_metadata import LibraryMetadata
from infra.storage.book_storage import BookStorage

class Library:

    def __init__(self, storage_root: Optional[Path] = None):

        self.storage_root = storage_root or Config.book_storage_root

        self._storage = LibraryStorage(storage_root=self.storage_root)
        self._metadata = LibraryMetadata(storage_root=self.storage_root)

    def add_books(self, pdf_paths: List[Path], run_ocr: bool = False) -> Dict[str, Any]:

        from infra.utils.ingest import add_books_to_library

        result = add_books_to_library(
            pdf_paths=pdf_paths,
            storage_root=self.storage_root,
            run_ocr=run_ocr
        )

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

        result = self._storage.delete_scan(
            scan_id=scan_id,
            delete_files=delete_files,
            remove_empty_book=remove_empty_book
        )

        self._remove_book_from_shuffles(scan_id)

        return result

    def get_book_storage(self, scan_id: str) -> BookStorage:

        return self._storage.get_book_storage(scan_id)

    def get_book_info(self, scan_id: str) -> Optional[Dict[str, Any]]:

        return self._storage.get_scan_info(scan_id)

    def list_books(self) -> List[Dict[str, Any]]:

        return self._storage.list_all_books()

    def get_shuffle(self, defensive: bool = True) -> Optional[List[str]]:

        shuffle = self._metadata.get_shuffle()

        if shuffle is None:
            return None

        if not defensive:
            return shuffle

        existing_scan_ids = {book['scan_id'] for book in self.list_books()}
        valid_shuffle = [sid for sid in shuffle if sid in existing_scan_ids]

        if len(valid_shuffle) != len(shuffle):
            self._metadata.set_shuffle(valid_shuffle)

        return valid_shuffle

    def create_shuffle(
        self,
        reshuffle: bool = False,
        books: Optional[List[str]] = None
    ) -> List[str]:

        existing_shuffle = self.get_shuffle(defensive=True)

        if not reshuffle and existing_shuffle:
            if books is None:
                books = [book['scan_id'] for book in self.list_books()]

            existing_set = set(existing_shuffle)
            new_books = [sid for sid in books if sid not in existing_set]

            if new_books:
                random.shuffle(new_books)
                updated_shuffle = existing_shuffle + new_books
                self._metadata.set_shuffle(updated_shuffle)
                return updated_shuffle

            return existing_shuffle

        if books is None:
            books = [book['scan_id'] for book in self.list_books()]

        shuffled = books.copy()
        random.shuffle(shuffled)
        self._metadata.set_shuffle(shuffled)

        return shuffled

    def clear_shuffle(self):

        self._metadata.clear_shuffle()

    def has_shuffle(self) -> bool:

        return self._metadata.has_shuffle()

    def get_shuffle_info(self) -> Optional[Dict[str, Any]]:

        return self._metadata.get_shuffle_info()

    def _add_books_to_shuffles(self, scan_ids: List[str]):

        current_shuffle = self._metadata.get_shuffle()

        if current_shuffle:
            random.shuffle(scan_ids)
            updated_shuffle = current_shuffle + scan_ids
            self._metadata.set_shuffle(updated_shuffle)

    def _remove_book_from_shuffles(self, scan_id: str):

        current_shuffle = self._metadata.get_shuffle()

        if current_shuffle and scan_id in current_shuffle:
            updated_shuffle = [sid for sid in current_shuffle if sid != scan_id]
            self._metadata.set_shuffle(updated_shuffle)

    def get_stats(self) -> Dict[str, Any]:

        return self._storage.get_stats()

    def list_all_scans(self) -> List[Dict[str, Any]]:

        return self._storage.list_all_scans()

    def get_scan_info(self, scan_id: str) -> Optional[Dict[str, Any]]:

        return self._storage.get_scan_info(scan_id)
