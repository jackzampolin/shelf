"""Library-level book collection management"""

import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from infra.config import Config

class LibraryStorage:

    def __init__(self, storage_root: Path = None):

        self.storage_root = storage_root or Config.book_storage_root

        self._book_storage_cache: Dict[str, Any] = {}

        self.storage_root.mkdir(parents=True, exist_ok=True)

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

    def _get_pipeline_status(self, scan_id: str) -> Dict[str, str]:

        status = {}
        for stage_name in ['ocr', 'corrected', 'labels', 'merged']:
            status[stage_name] = 'not_started'
        return status

    def _calculate_book_cost(self, scan_id: str) -> float:

        from infra.storage.book_storage import BookStorage

        storage = self.get_book_storage(scan_id)
        total_cost = 0.0

        for stage_name in ['ocr', 'corrected', 'labels', 'merged']:
            stage_storage = storage.stage(stage_name)
            metrics_file = stage_storage.output_dir / 'metrics.json'

            if metrics_file.exists():
                stage_cost = stage_storage.metrics_manager.get_total_cost()
                total_cost += stage_cost

        return total_cost

    def list_all_books(self) -> List[Dict[str, Any]]:

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

        return self.list_all_books()

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

    def delete_scan(
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

        return {
            "scan_id": scan_id,
            "deleted_from_library": True,
            "files_deleted": files_deleted,
            "book_removed": files_deleted,
            "scan_dir": str(book_dir) if files_deleted else None
        }

    def get_book_storage(self, scan_id: str):

        from infra.storage.book_storage import BookStorage

        book_dir = self.storage_root / scan_id

        if not book_dir.exists():
            raise ValueError(f"Scan {scan_id} not found in library")

        if scan_id in self._book_storage_cache:
            return self._book_storage_cache[scan_id]

        storage = BookStorage(scan_id, storage_root=self.storage_root)
        self._book_storage_cache[scan_id] = storage

        return storage
