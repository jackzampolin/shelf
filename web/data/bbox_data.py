"""
Bounding box data access for extract-toc visualization.

Ground truth from disk (ADR 001).
One concept per file (ADR 006).
"""

from typing import Optional, Dict, Any, List
from infra.pipeline.storage.book_storage import BookStorage


def get_bbox_phases(storage: BookStorage) -> Dict[str, Any]:
    """
    Load all bbox phase data from disk for visualization.

    Returns dict with:
        - extracted: Phase 2 raw extraction (BboxPageExtraction per page)
        - verified: Phase 3 self-verified boxes (BboxPageVerified per page)
        - ocr: Phase 4 OCR text results (BboxPageOCR per page)
        - pages: List of page numbers with bbox data

    Returns empty phases if files don't exist.
    """
    stage_storage = storage.stage("extract-toc")

    result = {
        'extracted': {},
        'verified': {},
        'ocr': {},
        'pages': []
    }

    # Load Phase 2: Raw extraction
    extracted_path = stage_storage.output_dir / "bboxes_extracted.json"
    if extracted_path.exists():
        extracted_data = stage_storage.load_file("bboxes_extracted.json")
        if extracted_data and 'pages' in extracted_data:
            for page_data in extracted_data['pages']:
                page_num = page_data.get('page_num')
                if page_num:
                    result['extracted'][page_num] = page_data
                    if page_num not in result['pages']:
                        result['pages'].append(page_num)

    # Load Phase 3: Verified boxes
    verified_path = stage_storage.output_dir / "bboxes_verified.json"
    if verified_path.exists():
        verified_data = stage_storage.load_file("bboxes_verified.json")
        if verified_data and 'pages' in verified_data:
            for page_data in verified_data['pages']:
                page_num = page_data.get('page_num')
                if page_num:
                    result['verified'][page_num] = page_data
                    if page_num not in result['pages']:
                        result['pages'].append(page_num)

    # Load Phase 4: OCR results
    ocr_path = stage_storage.output_dir / "bboxes_ocr.json"
    if ocr_path.exists():
        ocr_data = stage_storage.load_file("bboxes_ocr.json")
        if ocr_data and 'pages' in ocr_data:
            for page_data in ocr_data['pages']:
                page_num = page_data.get('page_num')
                if page_num:
                    result['ocr'][page_num] = page_data
                    if page_num not in result['pages']:
                        result['pages'].append(page_num)

    # Sort pages
    result['pages'] = sorted(result['pages'])

    return result


def get_page_bboxes(storage: BookStorage, page_num: int, phase: str) -> Optional[Dict[str, Any]]:
    """
    Get bounding boxes for a specific page and phase.

    Args:
        storage: Book storage instance
        page_num: Page number
        phase: One of 'extracted', 'verified', 'ocr'

    Returns:
        Page bbox data or None if not found
    """
    phases = get_bbox_phases(storage)

    if phase not in phases:
        return None

    return phases[phase].get(page_num)
