"""
Label-structure stage data access.

Ground truth from disk (ADR 001).
"""

import csv
from typing import Optional, List, Dict, Any
from pathlib import Path
from infra.pipeline.storage.book_storage import BookStorage


def get_label_structure_report(storage: BookStorage) -> Optional[List[Dict[str, Any]]]:
    """
    Load label-structure report.csv from disk.

    Returns list of dicts with observation columns (same as label-pages):
    - scan_page_number: int
    - whitespace_zones: str (e.g., 'top,middle' or 'none')
    - whitespace_conf: float
    - continues_from_prev: bool
    - continues_to_next: bool
    - continuation_conf: float
    - heading_exists: bool
    - heading_text: str
    - heading_position: str
    - heading_conf: float
    - header_exists: bool
    - header_text: str
    - header_conf: float
    - footer_exists: bool
    - footer_text: str
    - footer_position: str
    - footer_conf: float
    - ornamental_break: bool
    - ornamental_break_position: str
    - ornamental_break_conf: float
    - footnotes_exist: bool
    - footnotes_conf: float
    - page_num_exists: bool
    - page_num_value: str
    - page_num_position: str
    - page_num_conf: float

    Returns None if report.csv doesn't exist (stage not run yet).
    """
    stage_storage = storage.stage("label-structure")
    report_path = stage_storage.output_dir / "report.csv"

    if not report_path.exists():
        return None

    rows = []
    with open(report_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert scan_page_number to int
            row['scan_page_number'] = int(row['scan_page_number'])

            # Convert booleans
            row['continues_from_prev'] = row['continues_from_prev'].lower() == 'true'
            row['continues_to_next'] = row['continues_to_next'].lower() == 'true'
            row['heading_exists'] = row['heading_exists'].lower() == 'true'
            row['header_exists'] = row['header_exists'].lower() == 'true'
            row['footer_exists'] = row['footer_exists'].lower() == 'true'
            row['ornamental_break'] = row['ornamental_break'].lower() == 'true'
            row['footnotes_exist'] = row['footnotes_exist'].lower() == 'true'
            row['page_num_exists'] = row['page_num_exists'].lower() == 'true'

            # Convert confidence scores to float
            row['whitespace_conf'] = float(row['whitespace_conf']) if row['whitespace_conf'] else 0.0
            row['continuation_conf'] = float(row['continuation_conf']) if row['continuation_conf'] else 0.0
            row['heading_conf'] = float(row['heading_conf']) if row['heading_conf'] else 0.0
            row['header_conf'] = float(row['header_conf']) if row['header_conf'] else 0.0
            row['footer_conf'] = float(row['footer_conf']) if row['footer_conf'] else 0.0
            row['ornamental_break_conf'] = float(row['ornamental_break_conf']) if row['ornamental_break_conf'] else 0.0
            row['footnotes_conf'] = float(row['footnotes_conf']) if row['footnotes_conf'] else 0.0
            row['page_num_conf'] = float(row['page_num_conf']) if row['page_num_conf'] else 0.0

            rows.append(row)

    return rows


def get_page_labels(storage: BookStorage, page_num: int) -> Optional[Dict[str, Any]]:
    """
    Get labels for a specific page.

    Returns dict with all label data for the page, or None if not found.
    """
    report = get_label_structure_report(storage)

    if not report:
        return None

    for row in report:
        if row['scan_page_number'] == page_num:
            return row

    return None
