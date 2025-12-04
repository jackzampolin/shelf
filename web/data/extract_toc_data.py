from typing import Optional, Dict, Any
from infra.pipeline.storage.book_storage import BookStorage


def get_extract_toc_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    extract_toc_storage = storage.stage("extract-toc")
    toc_path = extract_toc_storage.output_dir / "toc.json"

    if not toc_path.exists():
        return None

    toc_data = extract_toc_storage.load_file("toc.json")

    if not toc_data:
        return None

    if 'toc' in toc_data:
        toc = toc_data['toc']
        entries = toc.get('entries', [])
        metadata = {
            'total_chapters': toc.get('total_chapters', 0),
            'total_sections': toc.get('total_sections', 0),
            'parsing_confidence': toc.get('parsing_confidence', 0.0),
            'notes': toc.get('notes', []),
        }
    else:
        entries = toc_data.get('entries', [])
        metadata = {
            'total_entries': toc_data.get('total_entries', len(entries)),
            'extraction_method': toc_data.get('extraction_method', 'unknown'),
            'toc_page_range': toc_data.get('toc_page_range'),
            'notes': toc_data.get('notes', []),
        }

    return {
        'toc_entries': entries,
        'toc_metadata': metadata
    }


def get_validation_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    extract_toc_storage = storage.stage("extract-toc")
    corrections_path = extract_toc_storage.output_dir / "corrections.json"

    if not corrections_path.exists():
        return None

    return extract_toc_storage.load_file("corrections.json")
