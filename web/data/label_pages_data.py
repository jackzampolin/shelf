"""
Label-pages stage data access.

Ground truth from disk (ADR 001).
"""

import csv
from typing import Optional, List, Dict, Any
from pathlib import Path
from infra.pipeline.storage.book_storage import BookStorage


def get_label_pages_report(storage: BookStorage) -> Optional[List[Dict[str, Any]]]:
    """
    Load label-pages report.csv from disk.

    Returns list of dicts with columns:
    - page_num: int
    - is_boundary: bool
    - boundary_conf: float
    - boundary_position: str
    - whitespace: str
    - page_density: str
    - starts_mid_sentence: bool
    - appears_to_continue: bool
    - has_boundary_marker: bool
    - boundary_marker_text: str

    Returns None if report.csv doesn't exist (stage not run yet).
    """
    stage_storage = storage.stage("label-pages")
    report_path = stage_storage.output_dir / "report.csv"

    if not report_path.exists():
        return None

    rows = []
    with open(report_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert page_num to int
            row['page_num'] = int(row['page_num'])

            # Convert booleans
            row['is_boundary'] = row['is_boundary'].lower() == 'true'
            row['starts_mid_sentence'] = row['starts_mid_sentence'].lower() == 'true'
            row['appears_to_continue'] = row['appears_to_continue'].lower() == 'true'
            row['has_boundary_marker'] = row['has_boundary_marker'].lower() == 'true'

            # Convert confidence score to float
            row['boundary_conf'] = float(row['boundary_conf']) if row['boundary_conf'] else 0.0

            rows.append(row)

    return rows


def get_page_labels(storage: BookStorage, page_num: int) -> Optional[Dict[str, Any]]:
    """
    Get labels for a specific page.

    Returns dict with all label data for the page, or None if not found.
    """
    report = get_label_pages_report(storage)

    if not report:
        return None

    for row in report:
        if row['page_num'] == page_num:
            return row

    return None
