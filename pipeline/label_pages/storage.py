from pathlib import Path
from typing import List, Optional
from PIL import Image

from infra.storage.book_storage import BookStorage


class LabelPagesStageStorage:
    def __init__(self, stage_name: str):
        self.stage_name = stage_name

    def list_completed_pages(self, storage: BookStorage) -> List[int]:
        return self.list_stage2_completed_pages(storage)

    def load_ocr_page(self, storage: BookStorage, page_num: int) -> Optional[dict]:
        from pipeline.ocr.storage import OCRStageStorage

        ocr_storage = OCRStageStorage(stage_name='ocr')
        return ocr_storage.load_selected_page(storage, page_num)

    def load_source_image(self, storage: BookStorage, page_num: int) -> Optional[Image.Image]:
        source_stage = storage.stage('source')
        image_file = source_stage.output_page(page_num, extension='png')

        if not image_file.exists():
            return None

        return Image.open(image_file)

    def get_report_path(self, storage: BookStorage) -> Path:
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.output_dir / "report.csv"

    def report_exists(self, storage: BookStorage) -> bool:
        return self.get_report_path(storage).exists()

    def get_stage1_dir(self, storage: BookStorage) -> Path:
        stage_storage = storage.stage(self.stage_name)
        stage1_dir = stage_storage.output_dir / "stage1"
        stage1_dir.mkdir(parents=True, exist_ok=True)
        return stage1_dir

    def save_stage1_result(
        self,
        storage: BookStorage,
        page_num: int,
        stage1_data: dict,
        cost_usd: float,
        metrics: dict = None,
    ):
        import json
        stage1_dir = self.get_stage1_dir(storage)
        output_file = stage1_dir / f"page_{page_num:04d}.json"

        stage1_data_with_meta = {
            **stage1_data,
            "cost_usd": cost_usd,
            "page_num": page_num,
        }

        with open(output_file, 'w') as f:
            json.dump(stage1_data_with_meta, f, indent=2)

        if metrics:
            stage_storage = storage.stage(self.stage_name)
            key = f"page_{page_num:04d}"
            stage_storage.metrics_manager.record(
                key=key,
                cost_usd=metrics.get('cost_usd', 0.0),
                time_seconds=metrics.get('total_time_seconds', 0.0),
                tokens=metrics.get('tokens_total'),
                custom_metrics={k: v for k, v in metrics.items()
                               if k not in ['cost_usd', 'total_time_seconds', 'tokens_total']},
                accumulate=False
            )

    def load_stage1_result(self, storage: BookStorage, page_num: int) -> Optional[dict]:
        import json
        stage1_dir = self.get_stage1_dir(storage)
        input_file = stage1_dir / f"page_{page_num:04d}.json"

        if not input_file.exists():
            return None

        with open(input_file, 'r') as f:
            return json.load(f)

    def list_stage1_completed_pages(self, storage: BookStorage) -> List[int]:
        stage1_dir = self.get_stage1_dir(storage)
        stage1_files = sorted(stage1_dir.glob("page_*.json"))
        page_nums = [int(p.stem.split('_')[1]) for p in stage1_files]
        return sorted(page_nums)

    def get_stage2_dir(self, storage: BookStorage) -> Path:
        stage_storage = storage.stage(self.stage_name)
        stage2_dir = stage_storage.output_dir / "stage2"
        stage2_dir.mkdir(parents=True, exist_ok=True)
        return stage2_dir

    def save_stage2_result(
        self,
        storage: BookStorage,
        page_num: int,
        data: dict,
        schema,
        cost_usd: float,
        metrics: dict = None,
    ):
        import json
        stage2_dir = self.get_stage2_dir(storage)
        output_file = stage2_dir / f"page_{page_num:04d}.json"

        validated = schema(**data)
        final_data = validated.model_dump()

        final_data['cost_usd'] = cost_usd
        final_data['page_num'] = page_num

        temp_file = output_file.with_suffix('.json.tmp')
        try:
            with open(temp_file, 'w') as f:
                json.dump(final_data, f, indent=2)
            temp_file.replace(output_file)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e

        if metrics:
            stage_storage = storage.stage(self.stage_name)
            key = f"page_{page_num:04d}"
            stage_storage.metrics_manager.record(
                key=key,
                cost_usd=metrics.get('cost_usd', 0.0),
                time_seconds=metrics.get('total_time_seconds', 0.0),
                tokens=metrics.get('tokens_total'),
                custom_metrics={k: v for k, v in metrics.items()
                               if k not in ['cost_usd', 'total_time_seconds', 'tokens_total']},
                accumulate=False
            )

    def load_stage2_result(self, storage: BookStorage, page_num: int) -> Optional[dict]:
        import json
        stage2_dir = self.get_stage2_dir(storage)
        input_file = stage2_dir / f"page_{page_num:04d}.json"

        if not input_file.exists():
            return None

        with open(input_file, 'r') as f:
            return json.load(f)

    def list_stage2_completed_pages(self, storage: BookStorage) -> List[int]:
        stage2_dir = self.get_stage2_dir(storage)
        stage2_files = sorted(stage2_dir.glob("page_*.json"))
        page_nums = [int(p.stem.split('_')[1]) for p in stage2_files]
        return sorted(page_nums)
