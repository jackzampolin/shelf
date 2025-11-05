from typing import List
from infra.storage.book_storage import BookStorage


class LabelPagesStageStorage:
    def __init__(self, stage_name: str):
        self.stage_name = stage_name

    def list_completed_pages(self, storage: BookStorage) -> List[int]:
        """List pages with final output (no longer uses stage2)."""
        stage_storage = storage.stage(self.stage_name)
        output_files = sorted(stage_storage.output_dir.glob("page_*.json"))
        page_nums = [int(p.stem.split('_')[1]) for p in output_files]
        return sorted(page_nums)

    def save_final_output(
        self,
        storage: BookStorage,
        page_num: int,
        data: dict,
        schema,
        cost_usd: float,
        result = None,
    ):
        """Save final label-pages output directly to output directory."""
        import json
        from infra.llm.metrics import record_llm_result

        stage_storage = storage.stage(self.stage_name)
        output_file = stage_storage.output_dir / f"page_{page_num:04d}.json"

        # Validate against schema
        validated = schema(**data)
        final_data = validated.model_dump()

        # Write with temp file for atomicity
        temp_file = output_file.with_suffix('.json.tmp')
        try:
            with open(temp_file, 'w') as f:
                json.dump(final_data, f, indent=2)
            temp_file.replace(output_file)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e

        # Record metrics
        if result:
            record_llm_result(
                metrics_manager=stage_storage.metrics_manager,
                key=f"page_{page_num:04d}",
                result=result,
                page_num=page_num,
                extra_fields={'stage': 'label-pages'}
            )

