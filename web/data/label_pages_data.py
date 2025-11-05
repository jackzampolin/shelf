"""
Label-pages stage data access.

Ground truth from disk (ADR 001).
"""

import csv
from typing import Optional, List, Dict, Any
from pathlib import Path
from infra.storage.book_storage import BookStorage


def get_label_pages_report(storage: BookStorage) -> Optional[List[Dict[str, Any]]]:
    """
    Load label-pages report.csv from disk.

    Returns list of dicts with columns:
    - page_num: int
    - printed_page_number: str (or empty)
    - numbering_style: str (none, roman, arabic)
    - page_number_location: str (none, header, footer)
    - page_region: str (front_matter, body, back_matter)
    - is_boundary: bool
    - boundary_type: str (or empty)
    - whitespace: str
    - heading_size: str
    - has_toc: bool
    - page_num_conf: float
    - region_conf: float
    - boundary_conf: float

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
            row['has_toc'] = row['has_toc'].lower() == 'true'

            # Convert confidence scores to floats
            row['page_num_conf'] = float(row['page_num_conf']) if row['page_num_conf'] else 0.0
            row['region_conf'] = float(row['region_conf']) if row['region_conf'] else 0.0
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
