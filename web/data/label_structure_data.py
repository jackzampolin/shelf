"""
Label-structure stage data access.

Ground truth from disk (ADR 001).
"""

from typing import Optional, List, Dict, Any
from infra.pipeline.storage.book_storage import BookStorage
from pipeline.label_structure.merge.processor import (
    get_base_merged_page,
    get_simple_fixes_merged_page,
    get_merged_page
)
from pipeline.label_structure.tools.report_generator import (
    generate_report_for_stage,
    calculate_sequence_validation
)
from pathlib import Path
import tempfile
import csv


def _generate_report_from_merge_fn(storage: BookStorage, merge_fn) -> Optional[List[Dict[str, Any]]]:
    from infra.pipeline.logger import PipelineLogger

    log_dir = storage.book_dir / "web_logs"
    logger = PipelineLogger(storage.scan_id, "web", log_dir, console_output=False)

    with tempfile.NamedTemporaryFile(mode='w+', suffix='.csv', delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        generate_report_for_stage(
            storage=storage,
            output_path=tmp_path,
            merge_fn=merge_fn,
            logger=logger,
            stage_name="web"
        )

        rows = []
        with open(tmp_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row['page_num'] = int(row['page_num'])
                row['header_present'] = row['header_present'].lower() == 'true'
                row['footer_present'] = row['footer_present'].lower() == 'true'
                row['page_num_present'] = row['page_num_present'].lower() == 'true'
                row['headings_present'] = row['headings_present'].lower() == 'true'
                row['headings_count'] = int(row['headings_count']) if row.get('headings_count') else 0
                row['sequence_gap'] = int(row['sequence_gap']) if row.get('sequence_gap') else 0
                row['needs_review'] = row.get('needs_review', '').lower() == 'true'
                rows.append(row)

        return rows
    finally:
        tmp_path.unlink(missing_ok=True)


def get_label_structure_report(storage: BookStorage, report_type: str = "full") -> Optional[List[Dict[str, Any]]]:
    stage_storage = storage.stage("label-structure")

    if not stage_storage.output_dir.exists():
        return None

    mechanical_dir = stage_storage.output_dir / "mechanical"
    if not mechanical_dir.exists() or not list(mechanical_dir.glob("page_*.json")):
        return None

    if report_type == "base":
        return _generate_report_from_merge_fn(storage, get_base_merged_page)
    elif report_type == "simple":
        return _generate_report_from_merge_fn(storage, get_simple_fixes_merged_page)
    else:
        return _generate_report_from_merge_fn(storage, get_merged_page)


def get_page_labels(storage: BookStorage, page_num: int, report_type: str = "full") -> Optional[Dict[str, Any]]:
    if report_type == "base":
        page_output = get_base_merged_page(storage, page_num)
    elif report_type == "simple":
        page_output = get_simple_fixes_merged_page(storage, page_num)
    else:
        page_output = get_merged_page(storage, page_num)

    return page_output.model_dump()
