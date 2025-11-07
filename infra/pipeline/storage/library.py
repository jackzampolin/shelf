import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List

from infra.config import Config
from infra.pipeline.storage.book_storage import BookStorage

class Library:
    def __init__(self, storage_root: Optional[Path] = None):
        self.storage_root = storage_root or Config.book_storage_root
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._book_storage_cache: Dict[str, BookStorage] = {}

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
        return add_books_to_library(
            pdf_paths=pdf_paths,
            storage_root=self.storage_root,
            run_ocr=run_ocr
        )

    def delete_book(self, scan_id: str) -> Dict[str, Any]:
        book_dir = self.storage_root / scan_id

        if not book_dir.exists():
            raise ValueError(f"Scan {scan_id} not found in library")

        try:
            shutil.rmtree(book_dir)
        except Exception as e:
            raise RuntimeError(f"Failed to delete scan directory {book_dir}: {e}") from e

        if scan_id in self._book_storage_cache:
            del self._book_storage_cache[scan_id]

        return {
            "scan_id": scan_id,
            "scan_dir": str(book_dir)
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
