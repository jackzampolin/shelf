from typing import Dict, Any, List, Set
from enum import Enum

from infra.storage.book_storage import BookStorage
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
    def __init__(self, stage_name: str, provider_names: List[str]):
        self.stage_name = stage_name
        self.provider_names = provider_names
        self.storage = OCRStageStorage(stage_name=stage_name)

    def get_status(
        self,
        storage: BookStorage,
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
            storage, all_pages, provider_remaining, selected_pages
        )
        pages_for_auto_select = self._get_pages_for_auto_select(
            storage, selected_pages
        )
        pages_needing_vision = self._get_pages_needing_vision(
            storage, selected_pages
        )

        auto_selected, vision_selected = self._count_selection_methods(selection_map)

        selection_map_exists = (storage.book_dir / self.stage_name / "selection_map.json").exists()
        report_exists = (storage.book_dir / self.stage_name / "report.csv").exists()

        needs_metadata = self._needs_metadata_extraction(storage)
        metadata = storage.load_metadata()
        metadata_confidence = metadata.get("metadata_extraction_confidence", 0.0)

        status = self._determine_status(selected_pages, total_pages, storage)
        metrics = self._aggregate_metrics(storage)

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
                "stage_runtime_seconds": 0.0,
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
        storage: BookStorage,
        all_pages: Set[int],
        provider_remaining: Dict[str, List[int]],
        selected_pages: Set[int]
    ) -> List[int]:
        pages_with_all_providers = all_pages.copy()
        for remaining in provider_remaining.values():
            pages_with_all_providers -= set(remaining)

        stage_storage = storage.stage(self.stage_name)

        pages_needing_agreement = []
        for page_num in pages_with_all_providers:
            if page_num in selected_pages:
                continue

            metrics = stage_storage.metrics_manager.get(f"page_{page_num:04d}")
            has_agreement = metrics and "provider_agreement" in metrics

            if not has_agreement:
                pages_needing_agreement.append(page_num)

        return sorted(pages_needing_agreement)

    def _get_pages_for_auto_select(
        self,
        storage: BookStorage,
        selected_pages: Set[int]
    ) -> List[int]:
        pages_for_auto_select = []

        stage_storage = storage.stage(self.stage_name)
        all_metrics = stage_storage.metrics_manager.get_all()

        for page_key, metrics in all_metrics.items():
            try:
                page_num = int(page_key.split('_')[1])
            except (IndexError, ValueError):
                continue

            if page_num in selected_pages:
                continue

            agreement = metrics.get("provider_agreement")

            if agreement is not None and agreement >= 0.95:
                pages_for_auto_select.append(page_num)

        return sorted(pages_for_auto_select)

    def _get_pages_needing_vision(
        self,
        storage: BookStorage,
        selected_pages: Set[int]
    ) -> List[int]:
        pages_needing_vision = []

        stage_storage = storage.stage(self.stage_name)
        all_metrics = stage_storage.metrics_manager.get_all()

        for page_key, metrics in all_metrics.items():
            try:
                page_num = int(page_key.split('_')[1])
            except (IndexError, ValueError):
                continue

            if page_num in selected_pages:
                continue

            agreement = metrics.get("provider_agreement")

            if agreement is not None and agreement < 0.95:
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
        storage: BookStorage
    ) -> str:
        if len(selected_pages) == 0:
            return OCRStageStatus.NOT_STARTED.value
        elif len(selected_pages) == total_pages:
            return OCRStageStatus.COMPLETED.value
        else:
            return "in_progress"

    def _aggregate_metrics(self, storage: BookStorage) -> Dict[str, Any]:
        stage_storage = storage.stage(self.stage_name)

        total_cost = stage_storage.metrics_manager.get_total_cost()
        total_time = stage_storage.metrics_manager.get_total_time()
        total_tokens = stage_storage.metrics_manager.get_total_tokens()

        # Get stored runtime from stage execution (actual wall-clock processing time)
        # This is the actual time spent processing, excluding gaps/interruptions
        # Shows 0.0 until the stage has been run with runtime tracking enabled
        runtime_metrics = stage_storage.metrics_manager.get("stage_runtime")
        stage_runtime = runtime_metrics.get("time_seconds", 0.0) if runtime_metrics else 0.0

        vision_cost = 0.0
        vision_tokens = 0

        selection_map = self.storage.load_selection_map(storage)
        for page_key, selection in selection_map.items():
            if selection.get("method") == "vision":
                page_num = int(page_key)
                metrics = stage_storage.metrics_manager.get(f"page_{page_num:04d}") or {}
                vision_cost += metrics.get("cost_usd", 0.0)
                vision_tokens += metrics.get("tokens", 0)

        return {
            "total_cost_usd": total_cost,
            "total_tokens": total_tokens,
            "total_time_seconds": total_time,
            "stage_runtime_seconds": stage_runtime,
            "vision_cost_usd": vision_cost,
            "vision_tokens": vision_tokens,
        }
