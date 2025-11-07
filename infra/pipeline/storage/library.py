import json
import shutil
import threading
import tempfile
import random
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from infra.config import Config
from infra.pipeline.storage.book_storage import BookStorage

class Library:
    METADATA_VERSION = "1.0"
    METADATA_FILENAME = ".library.json"

    def __init__(self, storage_root: Optional[Path] = None):
        self.storage_root = storage_root or Config.book_storage_root
        self.storage_root.mkdir(parents=True, exist_ok=True)

        self._book_storage_cache: Dict[str, BookStorage] = {}
        self._metadata_file = self.storage_root / self.METADATA_FILENAME
        self._metadata_lock = threading.Lock()
        self._metadata_state = self._load_or_create_metadata()

    def _load_or_create_metadata(self) -> Dict[str, Any]:
        if self._metadata_file.exists():
            try:
                with open(self._metadata_file, 'r') as f:
                    state = json.load(f)

                if state.get('version') != self.METADATA_VERSION:
                    return self._create_new_metadata()

                if 'shuffle' not in state:
                    state['shuffle'] = None

                return state
            except Exception:
                return self._create_new_metadata()
        else:
            return self._create_new_metadata()

    def _create_new_metadata(self) -> Dict[str, Any]:
        return {
            "version": self.METADATA_VERSION,
            "shuffle": None
        }

    def _save_metadata(self):
        self._metadata_file.parent.mkdir(parents=True, exist_ok=True)

        fd, temp_path = tempfile.mkstemp(
            dir=self._metadata_file.parent,
            prefix=f"{self.METADATA_FILENAME}.tmp"
        )

        try:
            import os
            with os.fdopen(fd, 'w') as f:
                json.dump(self._metadata_state, f, indent=2)

            os.replace(temp_path, self._metadata_file)
        except Exception:
            try:
                import os
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    def _scan_book_directories(self) -> List[str]:
        scan_ids = []

        if not self.storage_root.exists():
            return scan_ids

        for item in self.storage_root.iterdir():
            if not item.is_dir():
                continue

            if item.name.startswith('.'):
                continue

            metadata_file = item / "metadata.json"
            source_dir = item / "source"

            if metadata_file.exists() or source_dir.exists():
                scan_ids.append(item.name)

        return sorted(scan_ids)

    def _read_metadata(self, scan_id: str) -> Optional[Dict[str, Any]]:
        metadata_file = self.storage_root / scan_id / "metadata.json"

        if not metadata_file.exists():
            return None

        try:
            with open(metadata_file, 'r') as f:
                return json.load(f)
        except Exception:
            return None

    def _calculate_book_cost(self, scan_id: str) -> float:
        book_dir = self.storage_root / scan_id
        total_cost = 0.0

        if not book_dir.exists():
            return total_cost

        for item in book_dir.iterdir():
            if not item.is_dir():
                continue
            if item.name in ['source', 'logs', '.git']:
                continue
            if item.name.startswith('.'):
                continue

            metrics_file = item / 'metrics.json'
            if metrics_file.exists():
                try:
                    with open(metrics_file) as f:
                        metrics_data = json.load(f)

                    for key, data in metrics_data.items():
                        if isinstance(data, dict):
                            total_cost += data.get('cost_usd', 0.0)
                except Exception:
                    pass

        return total_cost

    def add_books(self, pdf_paths: List[Path], run_ocr: bool = False) -> Dict[str, Any]:
        from infra.utils.ingest import add_books_to_library

        result = add_books_to_library(
            pdf_paths=pdf_paths,
            storage_root=self.storage_root,
            run_ocr=run_ocr
        )

        new_scan_ids = result['scan_ids']
        if new_scan_ids:
            with self._metadata_lock:
                current_shuffle = self._metadata_state.get('shuffle')
                if current_shuffle:
                    random.shuffle(new_scan_ids)
                    updated_order = current_shuffle.get('order', []) + new_scan_ids
                    self._metadata_state['shuffle'] = {
                        'created_at': current_shuffle.get('created_at'),
                        'order': updated_order
                    }
                    self._save_metadata()

        return result

    def delete_book(
        self,
        scan_id: str,
        delete_files: bool = True,
        remove_empty_book: bool = True
    ) -> Dict[str, Any]:
        book_dir = self.storage_root / scan_id

        if not book_dir.exists():
            raise ValueError(f"Scan {scan_id} not found in library")

        files_deleted = False
        if delete_files:
            try:
                shutil.rmtree(book_dir)
                files_deleted = True
            except Exception as e:
                raise RuntimeError(f"Failed to delete scan directory {book_dir}: {e}") from e

        with self._metadata_lock:
            current_shuffle = self._metadata_state.get('shuffle')
            if current_shuffle and scan_id in current_shuffle.get('order', []):
                updated_order = [sid for sid in current_shuffle['order'] if sid != scan_id]
                self._metadata_state['shuffle'] = {
                    'created_at': current_shuffle.get('created_at'),
                    'order': updated_order
                }
                self._save_metadata()

        return {
            "scan_id": scan_id,
            "deleted_from_library": True,
            "files_deleted": files_deleted,
            "book_removed": files_deleted,
            "scan_dir": str(book_dir) if files_deleted else None
        }

    def get_book_storage(self, scan_id: str) -> BookStorage:
        book_dir = self.storage_root / scan_id

        if not book_dir.exists():
            raise ValueError(f"Scan {scan_id} not found in library")

        if scan_id in self._book_storage_cache:
            return self._book_storage_cache[scan_id]

        storage = BookStorage(scan_id, storage_root=self.storage_root)
        self._book_storage_cache[scan_id] = storage

        return storage

    def list_books(self) -> List[Dict[str, Any]]:
        books = []
        scan_ids = self._scan_book_directories()

        for scan_id in scan_ids:
            metadata = self._read_metadata(scan_id)

            if not metadata:
                books.append({
                    "scan_id": scan_id,
                    "title": scan_id,
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
        return self.list_books()

    def get_scan_info(self, scan_id: str) -> Optional[Dict[str, Any]]:
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
        scan_ids = self._scan_book_directories()

        total_pages = 0
        total_cost = 0.0

        for scan_id in scan_ids:
            metadata = self._read_metadata(scan_id)
            if metadata:
                total_pages += metadata.get('total_pages', 0)

            total_cost += self._calculate_book_cost(scan_id)

        return {
            "total_books": len(scan_ids),
            "total_scans": len(scan_ids),
            "total_pages": total_pages,
            "total_cost_usd": round(total_cost, 2)
        }

    def get_shuffle(self, defensive: bool = True) -> Optional[List[str]]:
        with self._metadata_lock:
            shuffle_data = self._metadata_state.get('shuffle')
            if not shuffle_data:
                return None

            shuffle_order = shuffle_data.get('order', [])

            if not defensive:
                return shuffle_order

            existing_scan_ids = {book['scan_id'] for book in self.list_books()}
            valid_shuffle = [sid for sid in shuffle_order if sid in existing_scan_ids]

            if len(valid_shuffle) != len(shuffle_order):
                self._metadata_state['shuffle'] = {
                    'created_at': shuffle_data.get('created_at'),
                    'order': valid_shuffle
                }
                self._save_metadata()

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

                with self._metadata_lock:
                    self._metadata_state['shuffle'] = {
                        'created_at': datetime.now().isoformat(),
                        'order': updated_shuffle
                    }
                    self._save_metadata()

                return updated_shuffle

            return existing_shuffle

        if books is None:
            books = [book['scan_id'] for book in self.list_books()]

        shuffled = books.copy()
        random.shuffle(shuffled)

        with self._metadata_lock:
            self._metadata_state['shuffle'] = {
                'created_at': datetime.now().isoformat(),
                'order': shuffled
            }
            self._save_metadata()

        return shuffled

    def clear_shuffle(self):
        with self._metadata_lock:
            self._metadata_state['shuffle'] = None
            self._save_metadata()

    def has_shuffle(self) -> bool:
        with self._metadata_lock:
            shuffle_data = self._metadata_state.get('shuffle')
            return shuffle_data is not None and len(shuffle_data.get('order', [])) > 0

    def get_shuffle_info(self) -> Optional[Dict[str, Any]]:
        with self._metadata_lock:
            shuffle_data = self._metadata_state.get('shuffle')
            if not shuffle_data:
                return None
            return {
                'created_at': shuffle_data.get('created_at'),
                'count': len(shuffle_data.get('order', []))
            }
