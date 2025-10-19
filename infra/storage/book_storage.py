"""
Unified Book Storage Manager

Provides centralized access to all book directories, files, and metadata
with built-in safety checks and consistent file naming conventions.

Architecture:
- Core BookStorage class manages book-level paths and metadata
- Stage-specific view classes handle stage I/O operations
- Each stage view knows its dependencies and can validate inputs
- Each stage view integrates CheckpointManager for automatic progress tracking
"""

import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from infra.storage.checkpoint import CheckpointManager


class StageView(ABC):
    """
    Base class for stage-specific storage views.

    Each stage view provides:
    - Input/output directory access
    - Page file naming
    - Directory creation
    - Input validation
    - Integrated checkpoint management
    """

    def __init__(self, storage: 'BookStorage'):
        self.storage = storage
        self._lock = threading.Lock()
        self._checkpoint: Optional[CheckpointManager] = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Stage name (e.g., 'ocr', 'correction')"""
        pass

    @property
    @abstractmethod
    def output_dir(self) -> Path:
        """Primary output directory for this stage"""
        pass

    @property
    def dependencies(self) -> List[str]:
        """
        List of stage names this stage depends on.
        Override in subclasses to declare dependencies.
        """
        return []

    def output_page(self, page_num: int, extension: str = "json") -> Path:
        """Get output page file path: {output_dir}/page_{num:04d}.{ext}"""
        return self.output_dir / f"page_{page_num:04d}.{extension}"

    def list_output_pages(self, extension: str = "json") -> List[Path]:
        """List all output page files, sorted by page number"""
        if not self.output_dir.exists():
            return []
        pattern = f"page_*.{extension}"
        return sorted(self.output_dir.glob(pattern))

    def ensure_directories(self) -> Dict[str, Path]:
        """
        Create all required directories for this stage.
        Returns dictionary of created directories.
        """
        with self._lock:
            dirs = {
                'output': self.output_dir,
                'logs': self.storage.logs_dir,
                'checkpoints': self.storage.checkpoints_dir
            }

            for dir_path in dirs.values():
                dir_path.mkdir(parents=True, exist_ok=True)

            return dirs

    def validate_inputs(self) -> bool:
        """
        Validate that all required inputs for this stage exist.

        Returns:
            True if valid

        Raises:
            FileNotFoundError: If required inputs missing
        """
        # Check book directory exists
        if not self.storage.book_dir.exists():
            raise FileNotFoundError(f"Book directory not found: {self.storage.book_dir}")

        # Check dependencies (override in subclasses for specific checks)
        for dep in self.dependencies:
            # Basic check: dependency stage has outputs
            # Subclasses can override for more specific validation
            pass

        return True

    @property
    def checkpoint(self) -> CheckpointManager:
        """
        Get checkpoint manager for this stage (lazy initialization).

        The checkpoint is always available. Stages control how it's used:
        - checkpoint.reset() - Start fresh
        - checkpoint.get_remaining_pages() - Get pages to process
        - checkpoint.mark_completed() - Mark page done (or use save_page())
        - checkpoint.mark_stage_complete() - Mark stage done

        Automatically ensures directories are created when checkpoint is accessed.

        Returns:
            CheckpointManager instance for this stage
        """
        if self._checkpoint is None:
            # Ensure directories exist before creating checkpoint
            self.ensure_directories()

            # Detect output directory name from output_dir path
            output_dir_name = self.output_dir.name if self.output_dir else self.name

            self._checkpoint = CheckpointManager(
                scan_id=self.storage.scan_id,
                stage=self.name,
                storage_root=self.storage.storage_root,
                output_dir=output_dir_name
            )
        return self._checkpoint

    def save_page(
        self,
        page_num: int,
        data: Dict[str, Any],
        cost_usd: float = 0.0,
        processing_time: float = 0.0,
        extension: str = "json",
        metrics: Optional[Dict[str, Any]] = None
    ):
        """
        Save page output and update checkpoint atomically with detailed metrics.

        This is the recommended way to write stage outputs. It handles:
        - Atomic file writing
        - Checkpoint update
        - Cost tracking
        - Detailed metrics storage
        - Thread safety

        Args:
            page_num: Page number to save
            data: Page data (will be JSON-serialized)
            cost_usd: Processing cost for this page in USD (tracked in checkpoint)
            processing_time: Processing time in seconds (deprecated - use metrics)
            extension: File extension (default: "json")
            metrics: Optional detailed metrics dict (from LLMResult) containing:
                - ttft_seconds, execution_time_seconds, total_time_seconds
                - tokens_input, tokens_output, tokens_total
                - cost_usd, model_used, attempts, timestamp

        Example:
            storage.correction.save_page(
                page_num=42,
                data=correction_output,
                cost_usd=0.023,
                processing_time=4.2,
                metrics=extract_metrics_from_result(result)
            )
        """
        with self._lock:
            # Write output file atomically
            output_file = self.output_page(page_num, extension=extension)
            temp_file = output_file.with_suffix(f'.{extension}.tmp')

            try:
                # Write to temp file
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)

                # Atomic rename
                temp_file.replace(output_file)

                # Validate output before marking complete (catch corruption/invalid data)
                if not self.checkpoint.validate_page_output(page_num):
                    raise IOError(f"Page {page_num} output validation failed after write")

                # Update checkpoint with metrics (now that file is safely written and validated)
                self.checkpoint.mark_completed(page_num, cost_usd=cost_usd, metrics=metrics)

            except Exception as e:
                # Clean up temp file on failure
                if temp_file.exists():
                    temp_file.unlink()
                raise e

    def get_log_dir(self) -> Path:
        """
        Get logs directory for this stage.

        Returns:
            Path to stage-specific logs directory: {output_dir}/logs/

        Example:
            log_dir = storage.correction.get_log_dir()
            # Returns: ~/Documents/book_scans/{scan_id}/corrected/logs/
        """
        log_dir = self.output_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def clean_stage(self, confirm: bool = False) -> bool:
        """
        Clean/delete all stage outputs, checkpoint, and logs.

        Args:
            confirm: If False, prompts for confirmation before deleting

        Returns:
            True if cleaned, False if cancelled

        Example:
            if storage.correction.clean_stage(confirm=True):
                print("Correction stage cleaned")
        """
        import shutil

        # Count what will be deleted
        output_files = self.list_output_pages()
        checkpoint_file = self.storage.checkpoint_file(self.name)
        log_dir = self.output_dir / "logs"
        log_files = list(log_dir.glob("*.jsonl")) if log_dir.exists() else []

        print(f"\n🗑️  Clean {self.name} stage for: {self.storage.scan_id}")
        print(f"   Output files: {len(output_files)}")
        print(f"   Checkpoint: {'exists' if checkpoint_file.exists() else 'none'}")
        print(f"   Logs: {len(log_files)} files")

        if not confirm:
            response = input("\n   Proceed? (yes/no): ").strip().lower()
            if response != 'yes':
                print("   Cancelled.")
                return False

        # Delete output directory (includes all outputs and logs)
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
            print(f"   ✓ Deleted {len(output_files)} output files and {len(log_files)} log files")

        # Delete checkpoint
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            print(f"   ✓ Deleted checkpoint")

        # Update metadata (remove stage completion flags)
        try:
            self.storage.update_metadata({
                f'{self.name}_complete': False,
                f'{self.name}_completion_date': None,
                f'{self.name}_total_cost': None
            })
            print(f"   ✓ Reset metadata")
        except FileNotFoundError:
            pass  # Metadata doesn't exist, skip

        print(f"\n✅ {self.name.capitalize()} stage cleaned for {self.storage.scan_id}")
        return True


class SourceStageView(StageView):
    """Source material (PDFs and extracted PNGs)"""

    @property
    def name(self) -> str:
        return "source"

    @property
    def output_dir(self) -> Path:
        return self.storage.book_dir / "source"

    def source_page(self, page_num: int) -> Path:
        """Get source page image: source/page_{num:04d}.png"""
        return self.output_page(page_num, extension="png")

    def list_source_pages(self) -> List[Path]:
        """List all source page images"""
        return self.list_output_pages(extension="png")


class OCRStageView(StageView):
    """OCR stage (text extraction from source images)"""

    @property
    def name(self) -> str:
        return "ocr"

    @property
    def output_dir(self) -> Path:
        return self.storage.book_dir / "ocr"

    @property
    def images_dir(self) -> Path:
        """Directory for extracted images from pages"""
        return self.storage.book_dir / "images"

    @property
    def dependencies(self) -> List[str]:
        return ["source"]

    def input_page(self, page_num: int) -> Path:
        """Get input source image: source/page_{num:04d}.png"""
        return self.storage.source.source_page(page_num)

    def extracted_image(self, page_num: int, img_id: int) -> Path:
        """Get extracted image path: images/page_{num:04d}_img_{id:03d}.png"""
        return self.images_dir / f"page_{page_num:04d}_img_{img_id:03d}.png"

    def ensure_directories(self) -> Dict[str, Path]:
        """Create OCR output directory and images directory"""
        dirs = super().ensure_directories()
        with self._lock:
            self.images_dir.mkdir(parents=True, exist_ok=True)
            dirs['images'] = self.images_dir
        return dirs

    def validate_inputs(self) -> bool:
        """Check that source pages exist"""
        super().validate_inputs()

        source_pages = self.storage.source.list_source_pages()
        if not source_pages:
            raise FileNotFoundError(
                f"No source page images found in {self.storage.source.output_dir}. "
                f"Run 'ar library add' to extract pages first."
            )

        return True


class MetadataStageView(StageView):
    """
    Book metadata extraction (analyzes first 20 OCR pages).

    Note: Metadata is stored at book level (metadata.json), not per-page.
    This view provides validation and metadata operations.
    """

    @property
    def name(self) -> str:
        return "metadata"

    @property
    def output_dir(self) -> Path:
        """Metadata doesn't have a per-page output dir, returns book dir"""
        return self.storage.book_dir

    @property
    def dependencies(self) -> List[str]:
        return ["ocr"]

    def validate_inputs(self) -> bool:
        """Check that OCR outputs exist (need first ~20 pages)"""
        super().validate_inputs()

        ocr_pages = self.storage.ocr.list_output_pages()
        if len(ocr_pages) < 10:
            raise FileNotFoundError(
                f"Insufficient OCR pages for metadata extraction. "
                f"Found {len(ocr_pages)} pages, need at least 10. "
                f"Run OCR stage first."
            )

        return True


class CorrectionStageView(StageView):
    """Vision-based OCR correction"""

    @property
    def name(self) -> str:
        return "correction"

    @property
    def output_dir(self) -> Path:
        return self.storage.book_dir / "corrected"

    @property
    def dependencies(self) -> List[str]:
        return ["ocr", "metadata"]

    def input_page(self, page_num: int) -> Path:
        """Get OCR input page: ocr/page_{num:04d}.json"""
        return self.storage.ocr.output_page(page_num)

    def source_image(self, page_num: int) -> Path:
        """Get source image for vision correction: source/page_{num:04d}.png"""
        return self.storage.source.source_page(page_num)

    def validate_inputs(self) -> bool:
        """Check that OCR outputs and metadata exist"""
        super().validate_inputs()

        # Check OCR outputs exist
        ocr_pages = self.storage.ocr.list_output_pages()
        if not ocr_pages:
            raise FileNotFoundError(
                f"No OCR outputs found. Run OCR stage first."
            )

        # Check metadata exists
        if not self.storage.metadata_file.exists():
            raise FileNotFoundError(
                f"Book metadata not found. Run metadata extraction first."
            )

        return True


class LabelStageView(StageView):
    """Page labeling (block classification and page number extraction)"""

    @property
    def name(self) -> str:
        return "label"

    @property
    def output_dir(self) -> Path:
        return self.storage.book_dir / "labels"

    @property
    def dependencies(self) -> List[str]:
        return ["correction"]

    def input_page(self, page_num: int) -> Path:
        """Get OCR input page (labels work from OCR, not correction): ocr/page_{num:04d}.json"""
        return self.storage.ocr.output_page(page_num)

    def source_image(self, page_num: int) -> Path:
        """Get source image for vision labeling: source/page_{num:04d}.png"""
        return self.storage.source.source_page(page_num)

    def validate_inputs(self) -> bool:
        """Check that correction is complete"""
        super().validate_inputs()

        # Check correction outputs exist
        corrected_pages = self.storage.correction.list_output_pages()
        if not corrected_pages:
            raise FileNotFoundError(
                f"No correction outputs found. Run correction stage first."
            )

        return True


class MergeStageView(StageView):
    """Merge OCR, correction, and label data into final processed pages"""

    @property
    def name(self) -> str:
        return "merge"

    @property
    def output_dir(self) -> Path:
        return self.storage.book_dir / "processed"

    @property
    def dependencies(self) -> List[str]:
        return ["ocr", "correction", "label"]

    def ocr_page(self, page_num: int) -> Path:
        """Get OCR input: ocr/page_{num:04d}.json"""
        return self.storage.ocr.output_page(page_num)

    def correction_page(self, page_num: int) -> Path:
        """Get correction input: corrected/page_{num:04d}.json"""
        return self.storage.correction.output_page(page_num)

    def label_page(self, page_num: int) -> Path:
        """Get label input: labels/page_{num:04d}.json"""
        return self.storage.label.output_page(page_num)

    def validate_inputs(self) -> bool:
        """Check that OCR, correction, and label outputs exist"""
        super().validate_inputs()

        ocr_pages = self.storage.ocr.list_output_pages()
        corrected_pages = self.storage.correction.list_output_pages()
        label_pages = self.storage.label.list_output_pages()

        if not ocr_pages:
            raise FileNotFoundError("No OCR outputs found. Run OCR stage first.")

        if not corrected_pages:
            raise FileNotFoundError("No correction outputs found. Run correction stage first.")

        if not label_pages:
            raise FileNotFoundError("No label outputs found. Run label stage first.")

        # Check page counts match
        if len(ocr_pages) != len(corrected_pages) or len(ocr_pages) != len(label_pages):
            raise ValueError(
                f"Page count mismatch: OCR={len(ocr_pages)}, "
                f"Correction={len(corrected_pages)}, Label={len(label_pages)}. "
                f"All stages must process same pages."
            )

        return True


class StructureStageView(StageView):
    """
    Structure detection (chapters, sections, etc.)

    STUB: To be implemented later. Current structure stage is being refactored.
    """

    @property
    def name(self) -> str:
        return "structure"

    @property
    def output_dir(self) -> Path:
        return self.storage.book_dir / "chapters"

    @property
    def dependencies(self) -> List[str]:
        return ["merge"]

    def validate_inputs(self) -> bool:
        """Check that merge outputs exist"""
        super().validate_inputs()

        merged_pages = self.storage.merge.list_output_pages()
        if not merged_pages:
            raise FileNotFoundError(
                f"No merged outputs found. Run merge stage first."
            )

        return True


class BookStorage:
    """
    Unified storage manager for book processing pipeline.

    Provides centralized access to all book directories, files, and metadata
    with built-in safety checks and consistent file naming conventions.

    Usage:
        storage = BookStorage(scan_id="modest-lovelace")

        # Access stage-specific operations
        storage.correction.validate_inputs()
        storage.correction.ensure_directories()
        input_file = storage.correction.input_page(5)
        output_file = storage.correction.output_page(5)

        # Access book-level resources
        metadata = storage.load_metadata()
        checkpoint = storage.checkpoint_file('correction')
    """

    def __init__(self, scan_id: str, storage_root: Optional[Path] = None):
        """
        Initialize book storage manager.

        Args:
            scan_id: Book scan identifier (e.g., "modest-lovelace")
            storage_root: Base storage directory (default: ~/Documents/book_scans)

        Raises:
            FileNotFoundError: If book directory doesn't exist
        """
        self._scan_id = scan_id
        self._storage_root = Path(storage_root or Path.home() / "Documents" / "book_scans").expanduser()
        self._book_dir = self._storage_root / scan_id

        # Stage views (created lazily)
        self._source_view: Optional[SourceStageView] = None
        self._ocr_view: Optional[OCRStageView] = None
        self._metadata_view: Optional[MetadataStageView] = None
        self._correction_view: Optional[CorrectionStageView] = None
        self._label_view: Optional[LabelStageView] = None
        self._merge_view: Optional[MergeStageView] = None
        self._structure_view: Optional[StructureStageView] = None

        # Thread safety for metadata operations
        self._metadata_lock = threading.Lock()

    # ===== Core Properties =====

    @property
    def scan_id(self) -> str:
        """Scan identifier (e.g., 'modest-lovelace')"""
        return self._scan_id

    @property
    def storage_root(self) -> Path:
        """Storage root directory"""
        return self._storage_root

    @property
    def book_dir(self) -> Path:
        """Book directory: {storage_root}/{scan_id}/"""
        return self._book_dir

    @property
    def exists(self) -> bool:
        """Check if book directory exists"""
        return self._book_dir.exists()

    # ===== Stage Views (lazily created) =====

    @property
    def source(self) -> SourceStageView:
        """Source stage view"""
        if self._source_view is None:
            self._source_view = SourceStageView(self)
        return self._source_view

    @property
    def ocr(self) -> OCRStageView:
        """OCR stage view"""
        if self._ocr_view is None:
            self._ocr_view = OCRStageView(self)
        return self._ocr_view

    @property
    def metadata_stage(self) -> MetadataStageView:
        """Metadata extraction stage view"""
        if self._metadata_view is None:
            self._metadata_view = MetadataStageView(self)
        return self._metadata_view

    @property
    def correction(self) -> CorrectionStageView:
        """Correction stage view"""
        if self._correction_view is None:
            self._correction_view = CorrectionStageView(self)
        return self._correction_view

    @property
    def label(self) -> LabelStageView:
        """Label stage view"""
        if self._label_view is None:
            self._label_view = LabelStageView(self)
        return self._label_view

    @property
    def merge(self) -> MergeStageView:
        """Merge stage view"""
        if self._merge_view is None:
            self._merge_view = MergeStageView(self)
        return self._merge_view

    @property
    def structure(self) -> StructureStageView:
        """Structure stage view (STUB)"""
        if self._structure_view is None:
            self._structure_view = StructureStageView(self)
        return self._structure_view

    # ===== Book-Level Directories =====

    @property
    def logs_dir(self) -> Path:
        """Log files directory: logs/"""
        return self._book_dir / "logs"

    @property
    def checkpoints_dir(self) -> Path:
        """Checkpoint files directory: checkpoints/"""
        return self._book_dir / "checkpoints"

    # ===== Book-Level Files =====

    @property
    def metadata_file(self) -> Path:
        """Book metadata file: metadata.json"""
        return self._book_dir / "metadata.json"

    def checkpoint_file(self, stage: str) -> Path:
        """
        Get checkpoint file for a stage.

        Args:
            stage: Stage name (e.g., 'ocr', 'correction', 'label')

        Returns:
            Path to checkpoint file: checkpoints/{stage}.json
        """
        return self.checkpoints_dir / f"{stage}.json"

    # ===== Metadata Operations =====

    def _load_metadata_unsafe(self) -> Dict[str, Any]:
        """
        Internal method: Load metadata without acquiring lock.
        Use load_metadata() for thread-safe loading.
        """
        if not self.metadata_file.exists():
            raise FileNotFoundError(f"Metadata file not found: {self.metadata_file}")

        with open(self.metadata_file, 'r') as f:
            return json.load(f)

    def _save_metadata_unsafe(self, metadata: Dict[str, Any]):
        """
        Internal method: Save metadata without acquiring lock (atomic write).
        Use save_metadata() for thread-safe saving.
        """
        # Atomic write: write to temp file, then rename
        temp_file = self.metadata_file.with_suffix('.json.tmp')
        with open(temp_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        temp_file.replace(self.metadata_file)

    def load_metadata(self) -> Dict[str, Any]:
        """
        Load book metadata from metadata.json.

        Returns:
            Dictionary of metadata

        Raises:
            FileNotFoundError: If metadata.json doesn't exist
        """
        with self._metadata_lock:
            return self._load_metadata_unsafe()

    def save_metadata(self, metadata: Dict[str, Any]):
        """
        Save book metadata to metadata.json (atomic write).

        Args:
            metadata: Complete metadata dictionary to save
        """
        with self._metadata_lock:
            self._save_metadata_unsafe(metadata)

    def update_metadata(self, updates: Dict[str, Any]):
        """
        Update specific metadata fields (atomic).

        Args:
            updates: Dictionary of fields to update

        Example:
            storage.update_metadata({
                'correction_complete': True,
                'correction_total_cost': 5.25
            })
        """
        with self._metadata_lock:
            metadata = self._load_metadata_unsafe()
            metadata.update(updates)
            self._save_metadata_unsafe(metadata)

    # ===== Validation =====

    def validate_book(self) -> Dict[str, bool]:
        """
        Validate book directory structure.

        Returns:
            Dictionary of validation results:
            {
                'book_dir_exists': bool,
                'metadata_exists': bool,
                'source_dir_exists': bool,
                'has_source_pages': bool
            }
        """
        return {
            'book_dir_exists': self.book_dir.exists(),
            'metadata_exists': self.metadata_file.exists(),
            'source_dir_exists': self.source.output_dir.exists(),
            'has_source_pages': len(self.source.list_source_pages()) > 0
        }
