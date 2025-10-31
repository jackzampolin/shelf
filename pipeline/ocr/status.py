"""OCR stage status tracking via ground truth (files on disk)."""

import json
from pathlib import Path
from typing import Dict, Any, List, Set
from enum import Enum

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger

from .storage import OCRStageStorage


class OCRStageStatus(str, Enum):
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
        return status in [cls.NOT_STARTED, cls.COMPLETED]

    @classmethod
    def is_in_progress(cls, status: str) -> bool:
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


class OCRStatusTracker:
    """Ground truth: A page is complete when it appears in selection_map.json."""

    def __init__(self, stage_name: str, provider_names: List[str]):
        self.stage_name = stage_name
        self.provider_names = provider_names
        self.storage = OCRStageStorage(stage_name=stage_name)

    def get_progress(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        source_stage = storage.stage("source")
        source_pages = source_stage.list_output_pages(extension="png")
        total_pages = len(source_pages)

        if total_pages == 0:
            return self._empty_progress()

        selection_map = self._load_selection_map(storage)
        selected_pages = set(int(k) for k in selection_map.keys())
        all_pages = set(range(1, total_pages + 1))
        remaining_pages = sorted(all_pages - selected_pages)

        provider_remaining = self._get_provider_remaining(storage, all_pages)

        pages_needing_agreement = self._get_pages_needing_agreement(
            all_pages, provider_remaining, checkpoint, selected_pages
        )
        pages_for_auto_select = self._get_pages_for_auto_select(
            checkpoint, selected_pages
        )
        pages_needing_vision = self._get_pages_needing_vision(
            checkpoint, selected_pages
        )

        auto_selected, vision_selected = self._count_selection_methods(selection_map)

        selection_map_exists = (storage.book_dir / self.stage_name / "selection_map.json").exists()
        report_exists = (storage.book_dir / self.stage_name / "report.csv").exists()

        needs_metadata = self._needs_metadata_extraction(storage)
        metadata = storage.load_metadata()
        metadata_confidence = metadata.get("metadata_extraction_confidence", 0.0)

        status = self._determine_status(selected_pages, total_pages, checkpoint)
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

    def _empty_progress(self) -> Dict[str, Any]:
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
        return self.storage.load_selection_map(storage)

    def _get_provider_remaining(
        self,
        storage: BookStorage,
        all_pages: Set[int]
    ) -> Dict[str, List[int]]:
        # Batch directory listings: 3 globs vs 1164 existence checks
        provider_remaining = {}

        for provider_name in self.provider_names:
            provider_dir = self.storage.get_provider_dir(storage, provider_name)

            if provider_dir.exists():
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
        pages_with_all_providers = all_pages.copy()
        for remaining in provider_remaining.values():
            pages_with_all_providers -= set(remaining)

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
        pages_for_auto_select = []

        checkpoint_state = checkpoint.get_status()
        page_metrics = checkpoint_state.get("page_metrics", {})

        for page_num_str, metrics in page_metrics.items():
            page_num = int(page_num_str)

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
        pages_needing_vision = []

        checkpoint_state = checkpoint.get_status()
        page_metrics = checkpoint_state.get("page_metrics", {})

        for page_num_str, metrics in page_metrics.items():
            page_num = int(page_num_str)

            if page_num in selected_pages:
                continue

            agreement = metrics.get("provider_agreement")
            has_selection = "selected_provider" in metrics

            if agreement is not None and agreement < 0.95 and not has_selection:
                pages_needing_vision.append(page_num)

        return sorted(pages_needing_vision)

    def _count_selection_methods(self, selection_map: Dict[str, Any]) -> tuple:
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
        metadata = storage.load_metadata()

        confidence = metadata.get("metadata_extraction_confidence", 0.0)
        if confidence < 0.5:
            return True

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
        if len(selected_pages) == 0:
            return OCRStageStatus.NOT_STARTED.value
        elif len(selected_pages) == total_pages:
            return OCRStageStatus.COMPLETED.value
        else:
            checkpoint_state = checkpoint.get_status()
            phase = checkpoint_state.get("phase", "in_progress")

            try:
                OCRStageStatus(phase)
                return phase
            except ValueError:
                return "in_progress"

    def _aggregate_metrics(self, checkpoint: CheckpointManager) -> Dict[str, Any]:
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

                if metrics.get("selection_method") == "vision":
                    vision_cost += cost
                    vision_tokens += tokens

        total_time = checkpoint_state.get("elapsed_time", 0.0)

        return {
            "total_cost_usd": total_cost,
            "total_tokens": total_tokens,
            "total_time_seconds": total_time,
            "vision_cost_usd": vision_cost,
            "vision_tokens": vision_tokens,
        }
