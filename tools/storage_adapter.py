"""
Storage Adapter for Shelf Viewer

Provides webapp-friendly interface to pipeline storage abstractions.
Wraps BookStorage, StageStorage, and CheckpointManager with convenient
methods for the Flask application.

This adapter eliminates duplicate code by using the pipeline's existing
abstractions while providing backwards-compatible APIs for the webapp.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any, Type
import os
import sys
import importlib.util

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import BaseModel

from infra.storage.book_storage import BookStorage
from infra.storage.library_storage import LibraryStorage

# Import stage schemas directly without triggering __init__.py
# This avoids heavy dependencies (cv2, etc.) that stages have
def _import_schema_module(module_path: Path):
    """Import a schemas module directly from file path."""
    spec = importlib.util.spec_from_file_location("schemas", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

_project_root = Path(__file__).parent.parent
_ocr_schemas = _import_schema_module(_project_root / "pipeline" / "ocr" / "schemas.py")
_correction_schemas = _import_schema_module(_project_root / "pipeline" / "correction" / "schemas.py")
_label_schemas = _import_schema_module(_project_root / "pipeline" / "label" / "schemas.py")
_merged_schemas = _import_schema_module(_project_root / "pipeline" / "merged" / "schemas.py")
_structure_schemas = _import_schema_module(_project_root / "pipeline" / "build_structure" / "schemas.py")

OCRPageOutput = _ocr_schemas.OCRPageOutput
CorrectionPageOutput = _correction_schemas.CorrectionPageOutput
LabelPageOutput = _label_schemas.LabelPageOutput
MergedPageOutput = _merged_schemas.MergedPageOutput
TableOfContents = _structure_schemas.TableOfContents

# Schema map: stage_name -> output schema
STAGE_SCHEMAS = {
    "ocr": OCRPageOutput,
    "corrected": CorrectionPageOutput,
    "labels": LabelPageOutput,
    "merged": MergedPageOutput,
}


class ViewerStorageAdapter:
    """
    Adapter providing webapp-friendly access to pipeline storage.

    Benefits over manual file access:
    - Type-safe schema validation
    - Thread-safe operations
    - Consistent with pipeline behavior
    - Automatic checkpoint management
    - No code duplication

    Example:
        adapter = ViewerStorageAdapter()

        # List all books
        books = adapter.find_all_books()

        # Access stage data
        ocr_data = adapter.get_page_data("modest-lovelace", "ocr", 42)

        # Get stage status
        status = adapter.get_stage_status("modest-lovelace", "corrected")
    """

    def __init__(self, storage_root: Optional[Path] = None):
        """
        Initialize adapter.

        Args:
            storage_root: Library root (default: ~/Documents/book_scans)
        """
        self.storage_root = Path(storage_root or os.getenv(
            "BOOK_STORAGE_ROOT",
            "~/Documents/book_scans"
        )).expanduser()

        # Cache BookStorage instances per scan_id
        self._book_cache: Dict[str, BookStorage] = {}

        # Library instance for library-wide operations
        self._library = LibraryStorage(storage_root=self.storage_root)

    def _get_storage(self, scan_id: str) -> BookStorage:
        """Get or create cached BookStorage instance."""
        if scan_id not in self._book_cache:
            self._book_cache[scan_id] = BookStorage(
                scan_id=scan_id,
                storage_root=self.storage_root
            )
        return self._book_cache[scan_id]

    # ===== Library Operations =====

    def find_all_books(self) -> List[Dict[str, Any]]:
        """
        Find all books in library with their stage statuses.

        Returns:
            List of book info dicts with keys:
            - scan_id: Book identifier
            - has_source: True if source images exist
            - ocr/corrected/labels/merged: Status dicts
            - has_toc: True if ToC extracted
        """
        books = []

        if not self.storage_root.exists():
            return books

        for book_dir in sorted(self.storage_root.iterdir()):
            if not book_dir.is_dir() or book_dir.name.startswith('.'):
                continue

            scan_id = book_dir.name
            storage = self._get_storage(scan_id)

            book_info = {
                "scan_id": scan_id,
                "has_source": storage.has_stage("source"),
            }

            # Get status for each pipeline stage
            for stage in ["ocr", "corrected", "labels", "merged"]:
                book_info[stage] = self.get_stage_status(scan_id, stage)

            # Check if ToC has actual data
            book_info["has_toc"] = self._has_valid_toc(scan_id)

            books.append(book_info)

        return books

    def _has_valid_toc(self, scan_id: str) -> bool:
        """Check if book has valid ToC data."""
        try:
            storage = self._get_storage(scan_id)
            toc_data = storage.stage("build_structure").load_file("toc.json")
            # Check for "No ToC found" note
            if "note" in toc_data and "No ToC found" in toc_data["note"]:
                return False
            return True
        except (FileNotFoundError, KeyError):
            return False

    # ===== Stage Status Operations =====

    def get_stage_status(self, scan_id: str, stage: str) -> Dict[str, Any]:
        """
        Get checkpoint status for a stage.

        Args:
            scan_id: Book identifier
            stage: Stage name

        Returns:
            Status dict with keys:
            - status: 'complete', 'in_progress', 'not_started', 'no_data'
            - completed: number of completed pages
            - total: total number of pages
        """
        storage = self._get_storage(scan_id)

        # Check if stage directory exists
        if not storage.has_stage(stage):
            return {"status": "no_data", "completed": 0, "total": 0}

        # Get status from checkpoint using pipeline's method
        checkpoint_data = storage.stage_status(stage)

        # Handle 'not_started' status
        if checkpoint_data.get('status') == 'not_started':
            return {"status": "not_started", "completed": 0, "total": 0}

        # Extract page metrics
        page_metrics = checkpoint_data.get("page_metrics", {})
        total = len(page_metrics)

        if total == 0:
            return {"status": "not_started", "completed": 0, "total": 0}

        # Count completed pages
        status = checkpoint_data.get("status", "unknown")
        if status == "completed":
            return {"status": "complete", "completed": total, "total": total}
        else:
            completed = sum(
                1 for metrics in page_metrics.values()
                if metrics.get("status") == "completed"
            )
            if completed == 0:
                return {"status": "not_started", "completed": 0, "total": total}
            else:
                return {"status": "in_progress", "completed": completed, "total": total}

    # ===== Page Data Operations =====

    def get_page_data(
        self,
        scan_id: str,
        stage: str,
        page_num: int,
        schema: Optional[Type[BaseModel]] = None,
        validate: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Load JSON data for a specific stage and page.

        Args:
            scan_id: Book identifier
            stage: Stage name
            page_num: Page number
            schema: Optional Pydantic model for validation (overrides auto-detection)
            validate: If True, use stage's default schema for validation

        Returns:
            Page data dict or None if not found

        Example:
            # Automatic schema validation
            data = adapter.get_page_data("modest-lovelace", "ocr", 42, validate=True)

            # Explicit schema
            from pipeline.ocr.schemas import OCRPageOutput
            data = adapter.get_page_data("modest-lovelace", "ocr", 42, schema=OCRPageOutput)
        """
        try:
            storage = self._get_storage(scan_id)

            # Auto-detect schema if validate=True
            if validate and schema is None:
                schema = STAGE_SCHEMAS.get(stage)

            return storage.stage(stage).load_page(
                page_num=page_num,
                extension="json",
                schema=schema
            )
        except FileNotFoundError:
            return None

    def get_stage_file(
        self,
        scan_id: str,
        stage: str,
        filename: str,
        schema: Optional[Type[BaseModel]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Load arbitrary file from stage directory.

        Args:
            scan_id: Book identifier
            stage: Stage name
            filename: File name (e.g., "toc.json")
            schema: Optional Pydantic model for validation

        Returns:
            File data dict or None if not found

        Example:
            # Load ToC with validation
            from pipeline.build_structure.schemas import ToCOutput
            toc = adapter.get_stage_file("modest-lovelace", "build_structure", "toc.json", schema=ToCOutput)
        """
        try:
            storage = self._get_storage(scan_id)
            return storage.stage(stage).load_file(
                filename=filename,
                schema=schema
            )
        except FileNotFoundError:
            return None

    def get_book_pages(self, scan_id: str) -> List[int]:
        """
        Get list of page numbers for a book.

        Args:
            scan_id: Book identifier

        Returns:
            Sorted list of page numbers
        """
        storage = self._get_storage(scan_id)

        # Try PNG first
        pages = storage.stage("source").list_output_pages(extension="png")
        if pages:
            return sorted([
                int(p.stem.split('_')[1])
                for p in pages
            ])

        # Try JPG
        pages = storage.stage("source").list_output_pages(extension="jpg")
        if pages:
            return sorted([
                int(p.stem.split('_')[1])
                for p in pages
            ])

        return []

    def get_page_image_path(self, scan_id: str, page_num: int) -> Optional[Path]:
        """
        Get path to source image for a page.

        Args:
            scan_id: Book identifier
            page_num: Page number

        Returns:
            Path to image file or None if not found
        """
        # Validate inputs
        if not scan_id or page_num < 1 or page_num > 9999:
            return None

        storage = self._get_storage(scan_id)

        # Try PNG first
        img_path = storage.stage("source").output_page(page_num, extension="png")
        if img_path.exists():
            return img_path

        # Try JPG
        img_path = storage.stage("source").output_page(page_num, extension="jpg")
        if img_path.exists():
            return img_path

        return None

    def get_page_image_dimensions(self, scan_id: str, page_num: int) -> tuple[int, int]:
        """
        Get image dimensions for a page.

        Args:
            scan_id: Book identifier
            page_num: Page number

        Returns:
            Tuple of (width, height) or (0, 0) if not found
        """
        from PIL import Image

        img_path = self.get_page_image_path(scan_id, page_num)
        if not img_path:
            return (0, 0)

        try:
            with Image.open(img_path) as img:
                return img.size
        except Exception:
            return (0, 0)

    # ===== Checkpoint & Metrics Operations =====

    def get_checkpoint_metrics(
        self,
        scan_id: str,
        stage: str
    ) -> Dict[int, Dict[str, Any]]:
        """
        Get all page metrics from checkpoint.

        Args:
            scan_id: Book identifier
            stage: Stage name

        Returns:
            Dict mapping page_num -> metrics dict
        """
        storage = self._get_storage(scan_id)
        checkpoint = storage.stage(stage).checkpoint
        return checkpoint.get_all_metrics()

    def get_stage_report_path(self, scan_id: str, stage: str) -> Optional[Path]:
        """
        Get path to stage report.csv file.

        Args:
            scan_id: Book identifier
            stage: Stage name

        Returns:
            Path to report.csv or None if doesn't exist
        """
        storage = self._get_storage(scan_id)
        report_path = storage.stage(stage).output_dir / "report.csv"
        return report_path if report_path.exists() else None

    # ===== Log Operations =====

    def get_stage_log_dir(self, scan_id: str, stage: str) -> Optional[Path]:
        """
        Get stage logs directory.

        Args:
            scan_id: Book identifier
            stage: Stage name

        Returns:
            Path to logs directory or None if doesn't exist
        """
        storage = self._get_storage(scan_id)
        log_dir = storage.stage(stage).get_log_dir()
        return log_dir if log_dir.exists() else None

    def get_latest_log_file(self, scan_id: str, stage: str) -> Optional[Path]:
        """
        Get latest log file for a stage.

        Args:
            scan_id: Book identifier
            stage: Stage name

        Returns:
            Path to latest log file or None
        """
        log_dir = self.get_stage_log_dir(scan_id, stage)
        if not log_dir:
            return None

        log_files = sorted(log_dir.glob(f"{stage}_*.jsonl"), reverse=True)
        return log_files[0] if log_files else None
