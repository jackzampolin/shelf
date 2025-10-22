"""
Unified Book Storage Manager

Provides centralized access to all book directories, files, and metadata
with built-in safety checks and consistent file naming conventions.

Architecture:
- Core BookStorage class manages book-level paths and metadata
- Generic StageStorage class handles stage I/O operations for any stage
- Each stage defines its dependencies and logic within its own module
- StageStorage integrates CheckpointManager for automatic progress tracking
"""

import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Type
from abc import ABC, abstractmethod
from pydantic import BaseModel
from infra.storage.checkpoint import CheckpointManager


class StageStorage:
    """
    Generic stage-specific storage manager.

    Provides storage operations for any pipeline stage:
    - Input/output directory access
    - Page file save/load with optional schema validation
    - Arbitrary file save/load
    - Directory creation
    - Integrated checkpoint management

    All stage-specific logic lives in the stage module itself.
    This class is purely for storage operations.

    Thread Safety & Lock Ordering:
    - Uses self._lock (threading.RLock - reentrant) for all I/O operations
    - RLock allows same thread to acquire lock multiple times (needed for ensure_directories)
    - LOCK ORDERING POLICY: Always acquire locks in this order to prevent deadlocks:
        1. LibraryStorage._lock
        2. BookStorage._metadata_lock
        3. StageStorage._lock (this class)
    - checkpoint property uses double-checked locking for thread-safe lazy initialization
    """

    def __init__(self, storage: 'BookStorage', name: str, dependencies: Optional[List[str]] = None):
        """
        Initialize stage storage.

        Args:
            storage: Parent BookStorage instance
            name: Stage name (e.g., 'ocr', 'corrected', 'detect-chapters')
            dependencies: Optional list of stage names this stage depends on
        """
        self.storage = storage
        self._name = name
        self._dependencies = dependencies or []
        # Use RLock (reentrant lock) to allow same thread to acquire multiple times
        # This is needed because checkpoint property calls ensure_directories() which also acquires lock
        self._lock = threading.RLock()
        self._checkpoint: Optional[CheckpointManager] = None

    @property
    def name(self) -> str:
        """Stage name (e.g., 'ocr', 'correction')"""
        return self._name

    @property
    def output_dir(self) -> Path:
        """Primary output directory for this stage"""
        return self.storage.book_dir / self._name

    @property
    def dependencies(self) -> List[str]:
        """
        List of stage names this stage depends on.
        """
        return self._dependencies

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
                'output': self.output_dir
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

        Uses double-checked locking for thread-safe lazy initialization.
        RLock allows same thread to acquire lock multiple times (needed because
        ensure_directories() also acquires the lock).

        Returns:
            CheckpointManager instance for this stage
        """
        if self._checkpoint is None:
            with self._lock:
                # Double-check after acquiring lock
                if self._checkpoint is None:
                    # Ensure directories exist before creating checkpoint
                    # Safe because we're using RLock (reentrant lock)
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
        metrics: Optional[Dict[str, Any]] = None,
        schema: Optional[Type[BaseModel]] = None
    ):
        """
        Save page output and update checkpoint atomically with detailed metrics.

        This is the recommended way to write stage outputs. It handles:
        - Atomic file writing
        - Optional schema validation (validates before write)
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
            schema: Optional Pydantic model for validation

        Example:
            from pipeline.2_correction.schemas import CorrectedPageOutput

            storage.correction.save_page(
                page_num=42,
                data=correction_output,
                cost_usd=0.023,
                processing_time=4.2,
                metrics=extract_metrics_from_result(result),
                schema=CorrectedPageOutput
            )
        """
        # Validate with schema if provided
        if schema:
            validated = schema(**data)
            data = validated.model_dump()

        # Get checkpoint reference (thread-safe lazy initialization with double-checked locking)
        checkpoint = self.checkpoint

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
                if not checkpoint.validate_page_output(page_num):
                    raise IOError(f"Page {page_num} output validation failed after write")

                # Update checkpoint with metrics (now that file is safely written and validated)
                checkpoint.mark_completed(page_num, cost_usd=cost_usd, metrics=metrics)

            except Exception as e:
                # Clean up temp file on failure
                if temp_file.exists():
                    temp_file.unlink()
                raise e

    def load_page(
        self,
        page_num: int,
        extension: str = "json",
        schema: Optional[Type[BaseModel]] = None
    ) -> Dict[str, Any]:
        """
        Load page output with optional schema validation.

        Args:
            page_num: Page number to load
            extension: File extension (default: "json")
            schema: Optional Pydantic model for validation

        Returns:
            Page data as dictionary

        Raises:
            FileNotFoundError: If page file doesn't exist
            ValidationError: If schema validation fails

        Example:
            from pipeline.2_correction.schemas import CorrectedPageOutput

            page_data = storage.correction.load_page(
                page_num=42,
                schema=CorrectedPageOutput
            )
        """
        output_file = self.output_page(page_num, extension=extension)

        if not output_file.exists():
            raise FileNotFoundError(f"Page {page_num} not found: {output_file}")

        with open(output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Validate with schema if provided
        if schema:
            validated = schema(**data)
            return validated.model_dump()

        return data

    def save_file(
        self,
        filename: str,
        data: Dict[str, Any],
        schema: Optional[Type[BaseModel]] = None
    ):
        """
        Save arbitrary file to stage output directory with optional schema validation.

        Args:
            filename: Name of file to save
            data: Data to save (will be JSON-serialized)
            schema: Optional Pydantic model for validation

        Example:
            from pipeline.5_structure.schemas import ChaptersOutput

            storage.structure.save_file(
                'chapters.json',
                chapters_data,
                schema=ChaptersOutput
            )
        """
        # Validate with schema if provided
        if schema:
            validated = schema(**data)
            data = validated.model_dump()

        with self._lock:
            # Write file atomically
            output_file = self.output_dir / filename
            temp_file = output_file.with_suffix('.tmp')

            try:
                # Write to temp file
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)

                # Atomic rename
                temp_file.replace(output_file)

            except Exception as e:
                # Clean up temp file on failure
                if temp_file.exists():
                    temp_file.unlink()
                raise e

    def load_file(
        self,
        filename: str,
        schema: Optional[Type[BaseModel]] = None
    ) -> Dict[str, Any]:
        """
        Load arbitrary file from stage output directory with optional schema validation.

        Args:
            filename: Name of file to load
            schema: Optional Pydantic model for validation

        Returns:
            File data as dictionary

        Raises:
            FileNotFoundError: If file doesn't exist
            ValidationError: If schema validation fails

        Example:
            from pipeline.5_structure.schemas import ChaptersOutput

            chapters = storage.structure.load_file(
                'chapters.json',
                schema=ChaptersOutput
            )
        """
        file_path = self.output_dir / filename

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Validate with schema if provided
        if schema:
            validated = schema(**data)
            return validated.model_dump()

        return data

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
            if storage.stage('correction').clean_stage(confirm=True):
                print("Correction stage cleaned")
        """
        import shutil

        # Count what will be deleted
        output_files = self.list_output_pages()
        checkpoint_file = self.output_dir / ".checkpoint"
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

        # Delete output directory (includes all outputs, checkpoint, and logs)
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
            print(f"   ✓ Deleted {len(output_files)} output files, checkpoint, and {len(log_files)} log files")

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


class BookStorage:
    """
    Unified storage manager for book processing pipeline.

    Provides centralized access to all book directories, files, and metadata
    with built-in safety checks and consistent file naming conventions.

    Usage:
        storage = BookStorage(scan_id="modest-lovelace")

        # Access stage-specific operations
        storage.stage('corrected').ensure_directories()
        storage.stage('corrected').save_page(5, data, schema=CorrectedPageOutput)
        data = storage.stage('corrected').load_page(5, schema=CorrectedPageOutput)

        # Access book-level resources
        metadata = storage.load_metadata()

    Thread Safety & Lock Ordering:
    - Uses self._metadata_lock (threading.Lock) for metadata operations
    - LOCK ORDERING POLICY: Always acquire locks in this order to prevent deadlocks:
        1. LibraryStorage._lock
        2. BookStorage._metadata_lock (this class)
        3. StageStorage._lock
    - Stage instances created via stage() method are cached and thread-safe
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

        # Cache for dynamically created stage storage instances
        self._stage_cache: Dict[str, StageStorage] = {}

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

    # ===== Generic Stage Access =====

    def stage(self, name: str) -> StageStorage:
        """
        Get storage for any stage dynamically.

        Args:
            name: Stage name (e.g., 'ocr', 'corrected', 'detect-chapters')

        Returns:
            StageStorage for the given stage

        Example:
            ocr_stage = storage.stage('ocr')
            chapters_stage = storage.stage('detect-chapters')
            ocr_stage.save_page(1, data, schema=OCRPageOutput)
        """
        if name not in self._stage_cache:
            self._stage_cache[name] = StageStorage(self, name)
        return self._stage_cache[name]

    def list_stages(self) -> List[str]:
        """
        List all existing stage folders.

        Returns:
            List of stage names (folder names)

        Example:
            >>> storage.list_stages()
            ['source', 'ocr', 'corrected', 'labels', 'processed']
        """
        if not self.book_dir.exists():
            return []

        stages = []
        for item in self.book_dir.iterdir():
            # Stage folders contain .checkpoint or page_*.json files
            if item.is_dir() and not item.name.startswith('.'):
                if (item / ".checkpoint").exists() or list(item.glob("page_*.json")):
                    stages.append(item.name)
        return sorted(stages)

    def has_stage(self, name: str) -> bool:
        """
        Check if stage folder exists.

        Args:
            name: Stage name

        Returns:
            True if stage folder exists

        Example:
            if storage.has_stage('ocr'):
                print("OCR complete")
        """
        return (self.book_dir / name).exists()

    def stage_status(self, name: str) -> Dict[str, Any]:
        """
        Get stage completion status from checkpoint.

        Args:
            name: Stage name

        Returns:
            Status dict with keys: status, completed_pages, total_pages, etc.
            Returns {'status': 'not_started'} if checkpoint doesn't exist

        Example:
            >>> storage.stage_status('ocr')
            {'status': 'completed', 'completed_pages': [1, 2, ..., 447], ...}
        """
        checkpoint_path = self.book_dir / name / '.checkpoint'
        if not checkpoint_path.exists():
            return {'status': 'not_started'}

        try:
            with open(checkpoint_path, 'r') as f:
                return json.load(f)
        except Exception:
            return {'status': 'unknown', 'error': 'Failed to read checkpoint'}

    # ===== Book-Level Files =====

    @property
    def metadata_file(self) -> Path:
        """Book metadata file: metadata.json"""
        return self._book_dir / "metadata.json"

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
        source_stage = self.stage('source')
        return {
            'book_dir_exists': self.book_dir.exists(),
            'metadata_exists': self.metadata_file.exists(),
            'source_dir_exists': source_stage.output_dir.exists(),
            'has_source_pages': len(source_stage.list_output_pages(extension='png')) > 0
        }
