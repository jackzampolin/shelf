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

    Returns list of dicts with columns:
    - page_num: int
    - header_present: bool
    - header_text: str
    - header_conf: str (high/medium/low)
    - header_source: str
    - footer_present: bool
    - footer_text: str
    - footer_conf: str
    - footer_source: str
    - page_num_present: bool
    - page_num_value: str
    - page_num_location: str
    - page_num_conf: str
    - page_num_source: str
    - headings_present: bool
    - headings_count: int
    - headings_text: str (pipe-separated)
    - headings_levels: str (pipe-separated)
    - headings_conf: str
    - headings_source: str

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
            # Convert page_num to int
            row['page_num'] = int(row['page_num'])

            # Convert booleans
            row['header_present'] = row['header_present'].lower() == 'true'
            row['footer_present'] = row['footer_present'].lower() == 'true'
            row['page_num_present'] = row['page_num_present'].lower() == 'true'
            row['headings_present'] = row['headings_present'].lower() == 'true'

            # Convert headings_count to int
            row['headings_count'] = int(row['headings_count']) if row.get('headings_count') else 0

            # Convert sequence_gap to int
            row['sequence_gap'] = int(row['sequence_gap']) if row.get('sequence_gap') else 0

            # Convert needs_review to bool
            row['needs_review'] = row.get('needs_review', '').lower() == 'true'

            rows.append(row)

    return rows


def get_page_labels(storage: BookStorage, page_num: int) -> Optional[Dict[str, Any]]:
    """
    Get full labels for a specific page from the page JSON file.

    Returns dict with all label data including:
    - headings, pattern_hints (from mechanical extraction)
    - header, footer, page_number (from structural metadata)
    - markers, footnotes, cross_references (from annotations)

    Returns None if page file not found.
    """
    stage_storage = storage.stage("label-structure")
    page_path = stage_storage.output_dir / f"page_{page_num:04d}.json"

    if not page_path.exists():
        return None

    import json
    with open(page_path, 'r') as f:
        return json.load(f)
