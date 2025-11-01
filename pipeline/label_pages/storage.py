from pathlib import Path
from typing import List, Optional
from PIL import Image

from infra.storage.book_storage import BookStorage


class LabelPagesStageStorage:

    def __init__(self, stage_name: str):
        self.stage_name = stage_name

    def list_completed_pages(self, storage: BookStorage) -> List[int]:
        stage_storage = storage.stage(self.stage_name)
        output_pages = stage_storage.list_output_pages(extension='json')
        # Extract page numbers from paths: page_0001.json -> 1
        page_nums = [int(p.stem.split('_')[1]) for p in output_pages]
        return sorted(page_nums)

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

    def save_labeled_page(
        self,
        storage: BookStorage,
        page_num: int,
        data: dict,
        schema,
        cost_usd: float,
        metrics: dict
    ):
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_page(
            page_num=page_num,
            data=data,
            schema=schema,
            cost_usd=cost_usd,
            metrics=metrics,
        )

    def get_report_path(self, storage: BookStorage) -> Path:
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.output_dir / "report.csv"

    def report_exists(self, storage: BookStorage) -> bool:
        return self.get_report_path(storage).exists()

    # Stage 1 intermediate storage
    def get_stage1_dir(self, storage: BookStorage) -> Path:
        """Get Stage 1 intermediate results directory."""
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
    ):
        """Save Stage 1 structural analysis result."""
        import json
        stage1_dir = self.get_stage1_dir(storage)
        output_file = stage1_dir / f"page_{page_num:04d}.json"

        # Add cost metadata
        stage1_data_with_meta = {
            **stage1_data,
            "cost_usd": cost_usd,
            "page_num": page_num,
        }

        with open(output_file, 'w') as f:
            json.dump(stage1_data_with_meta, f, indent=2)

    def load_stage1_result(self, storage: BookStorage, page_num: int) -> Optional[dict]:
        """Load Stage 1 result for a page."""
        import json
        stage1_dir = self.get_stage1_dir(storage)
        input_file = stage1_dir / f"page_{page_num:04d}.json"

        if not input_file.exists():
            return None

        with open(input_file, 'r') as f:
            return json.load(f)

    def list_stage1_completed_pages(self, storage: BookStorage) -> List[int]:
        """List pages that have Stage 1 results."""
        stage1_dir = self.get_stage1_dir(storage)
        stage1_files = sorted(stage1_dir.glob("page_*.json"))
        page_nums = [int(p.stem.split('_')[1]) for p in stage1_files]
        return sorted(page_nums)
