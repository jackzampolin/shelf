"""
OCR Stage V2 Status Tracker

Responsible for calculating progress by checking files on disk (ground truth).
Separates status tracking logic from the main stage implementation.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Set
from enum import Enum

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger

from .storage import OCRStageV2Storage


class OCRStageStatus(str, Enum):
    """
    OCR Stage V2 status progression.

    Ordered from start to completion, reflecting the actual pipeline flow.
    """
    NOT_STARTED = "not_started"
    RUNNING_OCR = "running-ocr"
    CALCULATING_AGREEMENT = "calculating-agreement"
    AUTO_SELECTING = "auto-selecting"
    RUNNING_VISION = "running-vision"
    EXTRACTING_METADATA = "extracting-metadata"
    GENERATING_REPORT = "generating-report"
    COMPLETED = "completed"

    @classmethod
    def is_terminal(cls, status: str) -> bool:
        """Check if status is terminal (not_started or completed)."""
        return status in [cls.NOT_STARTED, cls.COMPLETED]

    @classmethod
    def is_in_progress(cls, status: str) -> bool:
        """Check if status indicates active processing."""
        return status in [
            cls.RUNNING_OCR,
            cls.CALCULATING_AGREEMENT,
            cls.AUTO_SELECTING,
            cls.RUNNING_VISION,
            cls.EXTRACTING_METADATA,
            cls.GENERATING_REPORT
        ]

    @classmethod
    def get_order(cls, status: str) -> int:
        """Get numeric order for progress calculation (0-7)."""
        order_map = {
            cls.NOT_STARTED: 0,
            cls.RUNNING_OCR: 1,
            cls.CALCULATING_AGREEMENT: 2,
            cls.AUTO_SELECTING: 3,
            cls.RUNNING_VISION: 4,
            cls.EXTRACTING_METADATA: 5,
            cls.GENERATING_REPORT: 6,
            cls.COMPLETED: 7,
        }
        return order_map.get(status, 0)


class OCRStageV2Status:
    """
    Status tracker for OCR v2 stage.

    Ground truth: Files on disk, not checkpoint state.
    - A page is complete when it appears in selection_map.json
    - Provider completion is determined by file existence
    """

    def __init__(self, stage_name: str, provider_names: List[str]):
        """
        Args:
            stage_name: OCR stage name (e.g., "ocr_v2")
            provider_names: List of provider names to track
        """
        self.stage_name = stage_name
        self.provider_names = provider_names
        self.storage = OCRStageV2Storage(stage_name=stage_name)

    def get_progress(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        """
        Calculate stage progress by checking files on disk.

        Returns everything needed to resume pipeline at any point.

        Returns:
            {
                "total_pages": int,
                "remaining_pages": List[int],  # Pages without selection
                "status": "not_started" | "<checkpoint-phase>" | "completed",

                # OCR phase (Phase 1)
                "providers": {
                    "<provider-name>": List[int],  # Remaining pages for this provider
                },

                # Selection phase (Phase 2) - broken into sub-phases for resume
                "selection": {
                    "pages_needing_agreement": List[int],    # All providers done, no agreement yet
                    "pages_for_auto_select": List[int],      # Agreement >= 0.95, no selection yet
                    "pages_needing_vision": List[int],       # Agreement < 0.95, no selection yet
                    "auto_selected": int,                    # Count of automatic selections
                    "vision_selected": int,                  # Count of vision selections
                },

                # Artifacts
                "artifacts": {
                    "selection_map_exists": bool,  # selection_map.json generated
                    "report_exists": bool,         # report.csv generated
                },

                # Metrics
                "metrics": {
                    "total_cost_usd": float,
                    "total_tokens": int,
                    "total_time_seconds": float,
                    "vision_cost_usd": float,
                    "vision_tokens": int,
                },
            }
        """
        # Get total pages from source
        source_stage = storage.stage("source")
        source_pages = source_stage.list_output_pages(extension="png")
        total_pages = len(source_pages)

        if total_pages == 0:
            return self._empty_progress()

        # Load selection map (ground truth)
        selection_map = self._load_selection_map(storage)

        # Calculate remaining pages
        selected_pages = set(int(k) for k in selection_map.keys())
        all_pages = set(range(1, total_pages + 1))
        remaining_pages = sorted(all_pages - selected_pages)

        # Check provider completion
        provider_remaining = self._get_provider_remaining(storage, all_pages)

        # Calculate selection phase status (3 sub-phases)
        pages_needing_agreement = self._get_pages_needing_agreement(
            all_pages, provider_remaining, checkpoint, selected_pages
        )
        pages_for_auto_select = self._get_pages_for_auto_select(
            checkpoint, selected_pages
        )
        pages_needing_vision = self._get_pages_needing_vision(
            checkpoint, selected_pages
        )

        # Analyze selection methods
        auto_selected, vision_selected = self._count_selection_methods(selection_map)

        # Check artifact existence
        selection_map_exists = (storage.book_dir / self.stage_name / "selection_map.json").exists()
        report_exists = (storage.book_dir / self.stage_name / "report.csv").exists()

        # Check metadata extraction status
        needs_metadata = self._needs_metadata_extraction(storage)
        metadata = storage.load_metadata()
        metadata_confidence = metadata.get("metadata_extraction_confidence", 0.0)

        # Determine status
        status = self._determine_status(selected_pages, total_pages, checkpoint)

        # Aggregate metrics
        metrics = self._aggregate_metrics(checkpoint)

        return {
            "total_pages": total_pages,
            "remaining_pages": remaining_pages,
            "status": status,
            "providers": provider_remaining,
            "selection": {
                "pages_needing_agreement": pages_needing_agreement,
                "pages_for_auto_select": pages_for_auto_select,
                "pages_needing_vision": pages_needing_vision,
                "auto_selected": auto_selected,
                "vision_selected": vision_selected,
            },
            "metadata": {
                "needs_extraction": needs_metadata,
                "confidence": metadata_confidence,
            },
            "artifacts": {
                "selection_map_exists": selection_map_exists,
                "report_exists": report_exists,
            },
            "metrics": metrics,
        }

    # --- Private Helper Methods ---

    def _empty_progress(self) -> Dict[str, Any]:
        """Return empty progress structure for zero pages."""
        return {
            "total_pages": 0,
            "remaining_pages": [],
            "status": "not_started",
            "providers": {},
            "selection": {
                "pages_needing_agreement": [],
                "pages_for_auto_select": [],
                "pages_needing_vision": [],
                "auto_selected": 0,
                "vision_selected": 0,
            },
            "artifacts": {
                "selection_map_exists": False,
                "report_exists": False,
            },
            "metrics": {
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "total_time_seconds": 0.0,
                "vision_cost_usd": 0.0,
                "vision_tokens": 0,
            },
        }

    def _load_selection_map(self, storage: BookStorage) -> Dict[str, Any]:
        """Load selection map from disk (ground truth)."""
        return self.storage.load_selection_map(storage)

    def _get_provider_remaining(
        self,
        storage: BookStorage,
        all_pages: Set[int]
    ) -> Dict[str, List[int]]:
        """
        Get remaining pages for each provider using batch directory listings.

        More efficient than individual file checks (3 globs vs 1164 existence checks).
        """
        provider_remaining = {}

        for provider_name in self.provider_names:
            provider_dir = self.storage.get_provider_dir(storage, provider_name)

            if provider_dir.exists():
                # List all provider files once
                existing_files = set(provider_dir.glob("page_*.json"))
                existing_pages = set()

                for f in existing_files:
                    try:
                        page_num = int(f.stem.split('_')[1])
                        existing_pages.add(page_num)
                    except (IndexError, ValueError):
                        continue

                remaining = sorted(all_pages - existing_pages)
            else:
                # Provider directory doesn't exist = all pages remaining
                remaining = sorted(all_pages)

            provider_remaining[provider_name] = remaining

        return provider_remaining

    def _get_pages_needing_agreement(
        self,
        all_pages: Set[int],
        provider_remaining: Dict[str, List[int]],
        checkpoint: CheckpointManager,
        selected_pages: Set[int]
    ) -> List[int]:
        """
        Get pages that need agreement calculation (Phase 2a).

        Pages where:
        - All providers are complete
        - No agreement score in checkpoint yet
        - No selection yet
        """
        # Pages with all providers complete
        pages_with_all_providers = all_pages.copy()
        for remaining in provider_remaining.values():
            pages_with_all_providers -= set(remaining)

        # Filter to pages without agreement score and without selection
        pages_needing_agreement = []
        for page_num in pages_with_all_providers:
            if page_num in selected_pages:
                continue

            metrics = checkpoint.get_page_metrics(page_num)
            has_agreement = metrics and "provider_agreement" in metrics

            if not has_agreement:
                pages_needing_agreement.append(page_num)

        return sorted(pages_needing_agreement)

    def _get_pages_for_auto_select(
        self,
        checkpoint: CheckpointManager,
        selected_pages: Set[int]
    ) -> List[int]:
        """
        Get pages ready for auto-selection (Phase 2b).

        Pages where:
        - Agreement >= 0.95 (high agreement)
        - No selection yet
        """
        pages_for_auto_select = []

        checkpoint_state = checkpoint.get_status()
        page_metrics = checkpoint_state.get("page_metrics", {})

        for page_num_str, metrics in page_metrics.items():
            page_num = int(page_num_str)  # Checkpoint stores as string keys

            if page_num in selected_pages:
                continue

            agreement = metrics.get("provider_agreement")
            has_selection = "selected_provider" in metrics

            if agreement is not None and agreement >= 0.95 and not has_selection:
                pages_for_auto_select.append(page_num)

        return sorted(pages_for_auto_select)

    def _get_pages_needing_vision(
        self,
        checkpoint: CheckpointManager,
        selected_pages: Set[int]
    ) -> List[int]:
        """
        Get pages that need vision LLM call (Phase 2c).

        Pages where:
        - Agreement < 0.95 (low agreement)
        - No selection yet
        """
        pages_needing_vision = []

        checkpoint_state = checkpoint.get_status()
        page_metrics = checkpoint_state.get("page_metrics", {})

        for page_num_str, metrics in page_metrics.items():
            page_num = int(page_num_str)  # Checkpoint stores as string keys

            if page_num in selected_pages:
                continue

            agreement = metrics.get("provider_agreement")
            has_selection = "selected_provider" in metrics

            if agreement is not None and agreement < 0.95 and not has_selection:
                pages_needing_vision.append(page_num)

        return sorted(pages_needing_vision)

    def _count_selection_methods(self, selection_map: Dict[str, Any]) -> tuple:
        """Count automatic vs vision selections."""
        auto_selected = sum(
            1 for entry in selection_map.values()
            if entry.get("method") == "automatic"
        )
        vision_selected = sum(
            1 for entry in selection_map.values()
            if entry.get("method") == "vision"
        )
        return auto_selected, vision_selected

    def _needs_metadata_extraction(self, storage: BookStorage) -> bool:
        """
        Check if metadata extraction is needed.

        Returns True if:
        - metadata_extraction_confidence is missing or < 0.5, OR
        - Any core metadata field (title, author) is missing
        """
        metadata = storage.load_metadata()

        # Check confidence
        confidence = metadata.get("metadata_extraction_confidence", 0.0)
        if confidence < 0.5:
            return True

        # Check core fields are present (at minimum need title and author)
        core_fields = ["title", "author"]
        for field in core_fields:
            value = metadata.get(field)
            if value is None or (isinstance(value, str) and value.strip() == ""):
                return True

        return False

    def _determine_status(
        self,
        selected_pages: Set[int],
        total_pages: int,
        checkpoint: CheckpointManager
    ) -> str:
        """
        Determine stage status based on completion and checkpoint phase.

        Status progression:
        1. not_started: No pages selected
        2. running-ocr: Running OCR providers on pages
        3. calculating-agreement: Checking provider agreement
        4. auto-selecting: Auto-selecting high-agreement pages
        5. running-vision: Running vision model for low-agreement pages
        6. extracting-metadata: Extracting book metadata from first 15 pages
        7. generating-report: Creating report.csv from checkpoint metrics
        8. completed: All phases complete

        Returns:
            One of OCRStageStatus enum values
        """
        if len(selected_pages) == 0:
            return OCRStageStatus.NOT_STARTED.value
        elif len(selected_pages) == total_pages:
            return OCRStageStatus.COMPLETED.value
        else:
            # Use checkpoint phase as status (set by run() method)
            checkpoint_state = checkpoint.get_status()
            phase = checkpoint_state.get("phase", "in_progress")

            # Validate phase is a known status
            try:
                OCRStageStatus(phase)
                return phase
            except ValueError:
                # Fallback to generic in_progress if phase is unknown
                return "in_progress"

    def _aggregate_metrics(self, checkpoint: CheckpointManager) -> Dict[str, Any]:
        """Aggregate metrics from checkpoint."""
        checkpoint_state = checkpoint.get_status()

        total_cost = 0.0
        total_tokens = 0
        vision_cost = 0.0
        vision_tokens = 0

        page_metrics = checkpoint_state.get("page_metrics", {})
        for metrics in page_metrics.values():
            cost = metrics.get("cost_usd", 0.0)
            total_cost += cost

            usage = metrics.get("usage", {})
            if usage:
                tokens = usage.get("completion_tokens", 0)
                total_tokens += tokens

                # Track vision-specific costs
                if metrics.get("selection_method") == "vision":
                    vision_cost += cost
                    vision_tokens += tokens

        # Get total wall time from checkpoint
        total_time = checkpoint_state.get("elapsed_time", 0.0)

        return {
            "total_cost_usd": total_cost,
            "total_tokens": total_tokens,
            "total_time_seconds": total_time,
            "vision_cost_usd": vision_cost,
            "vision_tokens": vision_tokens,
        }
