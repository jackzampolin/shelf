"""
Clustering logic for gap healing agent system.

Groups related page number issues from report.csv into logical clusters
for targeted agent analysis.
"""
import csv
from pathlib import Path
from typing import List, Dict, Any
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


def read_report_csv(storage: BookStorage) -> List[Dict[str, Any]]:
    """Read report.csv and parse into structured data."""
    stage_storage = storage.stage("label-structure")
    csv_path = stage_storage.output_dir / "report.csv"

    rows = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields
            row['page_num'] = int(row['page_num'])

            # Parse detected page number value
            if row['page_num_value'] and row['page_num_value'].strip():
                try:
                    row['detected'] = int(row['page_num_value'])
                except ValueError:
                    # Keep as string (roman numerals, unparseable values)
                    row['detected'] = row['page_num_value']
            else:
                row['detected'] = None

            # Parse expected value
            if row['expected_value'] and row['expected_value'].strip():
                try:
                    row['expected'] = int(row['expected_value'])
                except ValueError:
                    row['expected'] = row['expected_value']
            else:
                row['expected'] = None

            # Rename for backward compatibility
            row['scan_page'] = row['page_num']
            row['status'] = row['sequence_status']

            rows.append(row)

    return rows


def identify_backward_jump_clusters(all_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Identify backward jump clusters.

    Pattern: backward_jump status followed by gap/cascade pages.
    These are typically chapter title pages where the chapter number
    was detected as the page number.
    """
    clusters = []

    # Build lookup by scan_page for efficient searching
    rows_by_page = {row['scan_page']: row for row in all_rows}

    for row in all_rows:
        if row['status'] == 'backward_jump':
            # Find the extent of the cascade
            cascade_pages = [row['scan_page']]

            # Look ahead for related gap pages
            current_page = row['scan_page']
            while True:
                next_page = current_page + 1
                if next_page not in rows_by_page:
                    break

                next_row = rows_by_page[next_page]

                # Stop if we hit a correctly sequenced page
                if next_row['status'] == 'ok':
                    break
                # Include gaps that immediately follow
                if next_row['status'].startswith('gap_'):
                    cascade_pages.append(next_page)
                    current_page = next_page
                else:
                    break

            clusters.append({
                'cluster_id': f"backward_jump_{row['scan_page']:04d}",
                'type': 'backward_jump',
                'scan_pages': cascade_pages,
                'priority': 'high',
                'detected_value': row['detected'],
                'expected_value': row['expected']
            })

    return clusters


def identify_ocr_error_clusters(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Identify OCR character substitution errors.

    Pattern: unparseable status with detectable character patterns like:
    - "13o" (O→0), "30I" (I→1), "1.11" (decimal artifacts)
    """
    clusters = []

    for row in rows:
        if row['status'] == 'unparseable':
            raw_value = row.get('detected_raw', row['detected'])

            clusters.append({
                'cluster_id': f"ocr_error_{row['scan_page']:04d}",
                'type': 'ocr_error',
                'scan_pages': [row['scan_page']],
                'priority': 'medium',
                'raw_value': raw_value,
                'expected_value': row['expected']
            })

    return clusters


def identify_structural_gap_clusters(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Identify structural gaps at part/chapter boundaries.

    Pattern: gap_3 to gap_6 (intentional design, not scanning errors)
    These often occur at chapter/part dividers.
    """
    clusters = []

    i = 0
    while i < len(rows):
        row = rows[i]

        # Look for gap_3 through gap_6 (structural gaps)
        if row['status'] in ['gap_3', 'gap_4', 'gap_5', 'gap_6']:
            gap_pages = [row['scan_page']]
            gap_type = row['status']

            # Find all consecutive pages in this gap
            j = i + 1
            gap_size = int(gap_type.split('_')[1])
            while len(gap_pages) < gap_size and j < len(rows):
                next_row = rows[j]
                if next_row['status'] == 'needs_review' or next_row['status'].startswith('gap_'):
                    gap_pages.append(next_row['scan_page'])
                    j += 1
                else:
                    break

            clusters.append({
                'cluster_id': f"structural_gap_{row['scan_page']:04d}",
                'type': 'structural_gap',
                'scan_pages': gap_pages,
                'priority': 'low',
                'gap_size': gap_size
            })

            i = j
            continue

        i += 1

    return clusters


def identify_mismatch_clusters(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Identify gap mismatches.

    Pattern: Actual gap size doesn't match expected gap size.
    Already flagged by mechanical healing as needing review.
    """
    clusters = []

    for row in rows:
        if row['status'].startswith('mismatch_gap_'):
            # Parse: "mismatch_gap_5_expected_3"
            parts = row['status'].split('_')
            actual_gap = int(parts[2])
            expected_gap = int(parts[4])

            clusters.append({
                'cluster_id': f"mismatch_{row['scan_page']:04d}",
                'type': 'gap_mismatch',
                'scan_pages': [row['scan_page']],
                'priority': 'high',
                'actual_gap': actual_gap,
                'expected_gap': expected_gap
            })

    return clusters


def identify_isolated_clusters(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Identify isolated issues that don't fit other patterns.

    These need individual attention from agents.
    """
    clusters = []

    for row in rows:
        # Check if this row is already covered by other clusters
        if row['status'] in ['isolated', 'edge_gap', 'multi_page_jump']:
            clusters.append({
                'cluster_id': f"isolated_{row['scan_page']:04d}",
                'type': row['status'],
                'scan_pages': [row['scan_page']],
                'priority': 'medium'
            })

    return clusters


def create_clusters(tracker, **kwargs) -> Dict[str, Any]:
    """
    Main clustering function.

    Reads report.csv and generates clusters.json for agent dispatch.
    """
    storage = tracker.storage
    logger = tracker.logger

    logger.info("=== Gap Healing: Creating issue clusters ===")

    # Read report
    rows = read_report_csv(storage)

    # Filter to only needs_review and related statuses
    # Keep: backward_jump, unparseable, gap_N, no_number (potential issues)
    # Skip: ok, first_page, type_change (normal sequencing)
    needs_review = [
        row for row in rows
        if row['status'] not in ['ok', 'first_page', 'type_change']
    ]

    logger.info(f"Found {len(needs_review)} pages needing review out of {len(rows)} total")

    # Identify clusters by type
    # Pass full rows list so functions can see 'ok' pages to stop cascades
    backward_jumps = identify_backward_jump_clusters(rows)
    ocr_errors = identify_ocr_error_clusters(needs_review)
    structural_gaps = identify_structural_gap_clusters(needs_review)
    mismatches = identify_mismatch_clusters(needs_review)
    isolated = identify_isolated_clusters(needs_review)

    all_clusters = (
        backward_jumps +
        ocr_errors +
        structural_gaps +
        mismatches +
        isolated
    )

    logger.info(f"Identified {len(all_clusters)} issue clusters:")
    logger.info(f"  - {len(backward_jumps)} backward jumps (chapter markers)")
    logger.info(f"  - {len(ocr_errors)} OCR errors")
    logger.info(f"  - {len(structural_gaps)} structural gaps")
    logger.info(f"  - {len(mismatches)} gap mismatches")
    logger.info(f"  - {len(isolated)} isolated issues")

    # Save clusters.json
    stage_storage = storage.stage("label-structure")
    clusters_data = {
        'total_clusters': len(all_clusters),
        'clusters_by_type': {
            'backward_jump': len(backward_jumps),
            'ocr_error': len(ocr_errors),
            'structural_gap': len(structural_gaps),
            'gap_mismatch': len(mismatches),
            'isolated': len(isolated)
        },
        'clusters': all_clusters
    }

    # Save to tracker's phase_dir
    import json
    output_path = tracker.phase_dir / 'clusters.json'
    output_path.write_text(json.dumps(clusters_data, indent=2))
    logger.info(f"Saved clusters.json with {len(all_clusters)} clusters")

    # Generate visualization
    from .visualize import generate_cluster_html
    viz_path = generate_cluster_html(storage, logger)
    logger.info(f"Cluster visualization: {viz_path}")

    return clusters_data
