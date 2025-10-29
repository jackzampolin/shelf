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
from infra.storage.library import Library

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
        self._library = Library(storage_root=self.storage_root)

    def _get_storage(self, scan_id: str) -> BookStorage:
        """Get or create cached BookStorage instance."""
        if scan_id not in self._book_cache:
            self._book_cache[scan_id] = BookStorage(
                scan_id=scan_id,
                storage_root=self.storage_root
            )
        return self._book_cache[scan_id]

    # ===== Library Operations =====

    def find_all_books(self, use_shuffle: bool = True) -> List[Dict[str, Any]]:
        """
        Find all books in library with their stage statuses.

        Args:
            use_shuffle: If True, return books in global shuffle order (default: True)

        Returns:
            List of book info dicts with keys:
            - scan_id: Book identifier
            - has_source: True if source images exist
            - ocr/corrected/labels/merged: Status dicts
            - has_toc: True if ToC extracted
        """
        if not self.storage_root.exists():
            return []

        # Collect all scan_ids
        all_scan_ids = []
        for book_dir in self.storage_root.iterdir():
            if book_dir.is_dir() and not book_dir.name.startswith('.'):
                all_scan_ids.append(book_dir.name)

        # Determine order
        if use_shuffle and self._library.has_shuffle():
            # Use global shuffle order (defensive filtering applied)
            shuffle = self._library.get_shuffle(defensive=True)
            # Preserve shuffle order but include any books not in shuffle at the end
            shuffle_set = set(shuffle) if shuffle else set()
            ordered_scan_ids = (shuffle or []) + sorted([sid for sid in all_scan_ids if sid not in shuffle_set])
        else:
            # Alphabetical order
            ordered_scan_ids = sorted(all_scan_ids)

        # Build book info list in order
        books = []
        for scan_id in ordered_scan_ids:
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

        # SPECIAL HANDLING FOR OCR: Multi-PSM checkpoints + reports
        if stage == "ocr":
            return self._get_ocr_status(storage)

        # Standard single-checkpoint handling for other stages
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

    def _get_ocr_status(self, storage: "BookStorage") -> Dict[str, Any]:
        """
        Get OCR stage status using multi-PSM checkpoint structure.

        OCR completion requires:
        1. All PSM checkpoints (psm3, psm4, psm6) have status == 'completed'
        2. All reports exist (psm_confidence_report.json, psm_agreement_report.json, psm_selection.json)

        Returns:
            Status dict with keys:
            - status: 'complete', 'in_progress', 'not_started', 'no_data'
            - completed: number of completed pages
            - total: total number of pages
        """
        ocr_dir = storage.stage('ocr').output_dir
        psm_modes = [3, 4, 6]  # Standard PSM modes

        # Get total pages from metadata
        try:
            metadata = storage.load_metadata()
            total_pages = metadata.get('total_pages', 0)
        except:
            total_pages = 0

        # If no total_pages in metadata, try to infer from source
        if total_pages == 0:
            try:
                source_pages = storage.stage('source').list_output_pages(extension='png')
                total_pages = len(source_pages)
            except:
                pass

        if total_pages == 0:
            return {"status": "no_data", "completed": 0, "total": 0}

        # Check if PSM-specific checkpoints exist (new multi-PSM structure)
        has_psm_checkpoints = any(
            (ocr_dir / f'psm{psm}' / '.checkpoint').exists()
            for psm in psm_modes
        )

        # BACKWARD COMPATIBILITY: Fall back to old single-checkpoint structure
        if not has_psm_checkpoints:
            # Try old root checkpoint
            root_checkpoint = ocr_dir / '.checkpoint'
            if root_checkpoint.exists():
                try:
                    import json
                    with open(root_checkpoint) as f:
                        root_data = json.load(f)

                    root_status = root_data.get('status', 'not_started')
                    root_metrics = root_data.get('page_metrics', {})
                    root_completed = len(root_metrics)

                    # Check if reports exist (even for old checkpoints)
                    required_reports = [
                        'psm_confidence_report.json',
                        'psm_agreement_report.json',
                        'psm_selection.json'
                    ]
                    all_reports_exist = all(
                        (ocr_dir / report).exists() for report in required_reports
                    )

                    # Complete if status is completed AND reports exist
                    if root_status == 'completed' and all_reports_exist:
                        return {"status": "complete", "completed": total_pages, "total": total_pages}
                    elif root_completed > 0:
                        return {"status": "in_progress", "completed": root_completed, "total": total_pages}
                    else:
                        return {"status": "not_started", "completed": 0, "total": total_pages}
                except:
                    pass

            # No valid checkpoints found
            return {"status": "not_started", "completed": 0, "total": total_pages}

        # NEW STRUCTURE: Check all PSM checkpoints
        all_psms_complete = True
        min_completed = total_pages

        for psm in psm_modes:
            psm_checkpoint_file = ocr_dir / f'psm{psm}' / '.checkpoint'

            if not psm_checkpoint_file.exists():
                all_psms_complete = False
                min_completed = 0
                continue

            try:
                import json
                with open(psm_checkpoint_file) as f:
                    psm_data = json.load(f)

                psm_status = psm_data.get('status', 'not_started')
                psm_metrics = psm_data.get('page_metrics', {})
                psm_completed = len(psm_metrics)

                # Track minimum completed across all PSMs
                min_completed = min(min_completed, psm_completed)

                # Accept either "completed" status OR all pages processed
                # (OCR pipeline bug: doesn't mark PSM checkpoints complete)
                if psm_status == 'not_started' or psm_completed < total_pages:
                    all_psms_complete = False
            except:
                all_psms_complete = False
                min_completed = 0

        # Check required reports exist
        required_reports = [
            'psm_confidence_report.json',
            'psm_agreement_report.json',
            'psm_selection.json'
        ]

        all_reports_exist = all(
            (ocr_dir / report).exists() for report in required_reports
        )

        # Determine status
        if all_psms_complete and all_reports_exist:
            return {"status": "complete", "completed": total_pages, "total": total_pages}
        elif min_completed > 0:
            return {"status": "in_progress", "completed": min_completed, "total": total_pages}
        else:
            return {"status": "not_started", "completed": 0, "total": total_pages}

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
