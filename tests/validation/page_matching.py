"""
Page number extraction and matching utilities.

Handles the mismatch between file page numbers and printed page numbers
in book scans. Essential for comparing different digitizations of the same book.
"""

import re
import json
from pathlib import Path
from typing import Optional, Dict, Tuple


def extract_printed_page_number(page_data: dict) -> Optional[int]:
    """
    Extract printed page number from OCR/corrected page data.

    Many books have printed page numbers in headers like:
    "30 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY..."

    Args:
        page_data: OCR or corrected page JSON dict

    Returns:
        Printed page number (int) or None if not found
    """
    # Look for page numbers in headers
    for region in page_data.get('regions', []):
        if region.get('type') == 'header':
            text = region.get('text', '')

            # Try to match number at start of header
            # Pattern: optional whitespace, then digits, then space/punctuation
            match = re.match(r'^\s*(\d+)\s+', text)
            if match:
                return int(match.group(1))

    # Also check in footers (some books have page numbers there)
    for region in page_data.get('regions', []):
        if region.get('type') == 'footer':
            text = region.get('text', '')

            # Center-aligned footer page numbers
            match = re.match(r'^\s*(\d+)\s*$', text.strip())
            if match:
                return int(match.group(1))

    return None


def build_page_mapping(scan_dir: Path, stage: str = "ocr") -> Dict[int, int]:
    """
    Build mapping from file page numbers to printed page numbers.

    Args:
        scan_dir: Root directory for scan (e.g., roosevelt-autobiography/)
        stage: Pipeline stage ("ocr", "corrected", etc.)

    Returns:
        Dictionary mapping file_page_num -> printed_page_num
        Example: {30: 10, 40: 20, 50: 30, ...}
    """
    stage_dirs = {
        "ocr": "ocr",
        "corrected": "corrected",
        "fix": "corrected",
    }

    stage_dir = stage_dirs.get(stage, stage)
    page_dir = scan_dir / stage_dir

    if not page_dir.exists():
        raise FileNotFoundError(f"Stage directory not found: {page_dir}")

    mapping = {}

    # Scan all page files
    for page_file in sorted(page_dir.glob('page_*.json')):
        # Extract file page number from filename
        file_page = int(page_file.stem.split('_')[1])

        # Load page data
        with open(page_file) as f:
            page_data = json.load(f)

        # Try to extract printed page number
        printed_page = extract_printed_page_number(page_data)

        if printed_page is not None:
            mapping[file_page] = printed_page

    return mapping


def find_offset(mapping: Dict[int, int]) -> Optional[int]:
    """
    Find consistent offset between file pages and printed pages.

    Args:
        mapping: Dict from file_page_num -> printed_page_num

    Returns:
        Offset (file_page - printed_page) if consistent, None if variable
    """
    if not mapping:
        return None

    # Calculate offsets
    offsets = [file_page - printed_page
              for file_page, printed_page in mapping.items()]

    # Check if offset is consistent (within 1 page)
    if len(set(offsets)) == 1:
        return offsets[0]

    # If offsets vary slightly, use the most common one
    from collections import Counter
    most_common_offset = Counter(offsets).most_common(1)[0][0]

    return most_common_offset


def find_matching_ia_page(printed_page_num: int,
                          ia_page_text_samples: Dict[int, str],
                          window: int = 5) -> Optional[int]:
    """
    Find which IA page corresponds to a printed page number.

    Searches IA pages that might contain the printed page number
    in their text content.

    Args:
        printed_page_num: Printed page number to find (e.g., 30)
        ia_page_text_samples: Dict of ia_page_num -> text for nearby pages
        window: How many pages to search around printed_page_num

    Returns:
        IA page number that likely matches, or None
    """
    # Look for the printed page number in IA text
    target_str = str(printed_page_num)

    # Search in a window around the printed page number
    for ia_page in range(printed_page_num - window,
                        printed_page_num + window + 1):
        if ia_page in ia_page_text_samples:
            text = ia_page_text_samples[ia_page]

            # Look for printed page number at start of text
            # (common in running headers)
            if re.match(rf'^\s*{target_str}\s+', text):
                return ia_page

    return None


def get_calibration_stats(scan_dir: Path, stage: str = "ocr") -> dict:
    """
    Get statistics about page number mapping for a scan.

    Args:
        scan_dir: Root directory for scan
        stage: Pipeline stage

    Returns:
        Dictionary with:
        - total_pages: Total pages found
        - pages_with_printed_nums: Count with extractable printed page numbers
        - offset: Consistent offset if found
        - offset_consistency: How consistent the offset is (0.0-1.0)
        - sample_mapping: First 10 entries of mapping
    """
    mapping = build_page_mapping(scan_dir, stage)
    offset = find_offset(mapping)

    # Calculate consistency
    if mapping:
        offsets = [fp - pp for fp, pp in mapping.items()]
        most_common_count = max(offsets.count(o) for o in set(offsets))
        consistency = most_common_count / len(offsets)
    else:
        consistency = 0.0

    # Get sample
    sample = dict(list(mapping.items())[:10])

    return {
        'total_pages': len(list((scan_dir / stage).glob('page_*.json'))),
        'pages_with_printed_nums': len(mapping),
        'offset': offset,
        'offset_consistency': consistency,
        'sample_mapping': sample,
    }
