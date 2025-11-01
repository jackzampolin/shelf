"""Book-level metadata helpers (per-book metadata.json)"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

def update_book_metadata(book_dir: Path, stage: str, metadata: Dict[str, Any]):

    metadata_file = book_dir / "metadata.json"

    if metadata_file.exists():
        with open(metadata_file, 'r') as f:
            book_metadata = json.load(f)
    else:
        book_metadata = {}

    if 'processing_history' not in book_metadata:
        book_metadata['processing_history'] = []

    processing_record = {
        'stage': stage,
        'timestamp': datetime.now().isoformat(),
        **metadata
    }

    book_metadata['processing_history'].append(processing_record)

    if stage == 'ocr':
        book_metadata['ocr_complete'] = True
        book_metadata['ocr_completion_date'] = datetime.now().isoformat()
        if 'pages_processed' in metadata:
            book_metadata['total_pages_processed'] = metadata['pages_processed']

    with open(metadata_file, 'w') as f:
        json.dump(book_metadata, f, indent=2)

def get_latest_processing_record(book_dir: Path, stage: str) -> Dict[str, Any]:

    metadata_file = book_dir / "metadata.json"

    if not metadata_file.exists():
        return None

    with open(metadata_file, 'r') as f:
        book_metadata = json.load(f)

    processing_history = book_metadata.get('processing_history', [])

    stage_records = [r for r in processing_history if r['stage'] == stage]

    return stage_records[-1] if stage_records else None

def get_scan_total_cost(book_dir: Path) -> float:

    metadata_file = book_dir / "metadata.json"

    if not metadata_file.exists():
        return 0.0

    with open(metadata_file, 'r') as f:
        book_metadata = json.load(f)

    processing_history = book_metadata.get('processing_history', [])

    return sum(
        record.get('cost_usd', 0)
        for record in processing_history
    )

def get_scan_models(book_dir: Path) -> Dict[str, str]:

    metadata_file = book_dir / "metadata.json"

    if not metadata_file.exists():
        return {}

    with open(metadata_file, 'r') as f:
        book_metadata = json.load(f)

    processing_history = book_metadata.get('processing_history', [])

    models = {}
    for record in processing_history:
        stage = record.get('stage')
        model = record.get('model')
        if stage and model:
            models[stage] = model

    return models

def format_processing_summary(book_dir: Path) -> str:

    metadata_file = book_dir / "metadata.json"

    if not metadata_file.exists():
        return "No processing metadata found."

    with open(metadata_file, 'r') as f:
        book_metadata = json.load(f)

    processing_history = book_metadata.get('processing_history', [])

    if not processing_history:
        return "No processing history found."

    summary_parts = []
    summary_parts.append("Processing Summary:")
    summary_parts.append("=" * 60)

    total_cost = 0.0

    for record in processing_history:
        stage = record.get('stage', 'unknown')
        timestamp = record.get('timestamp', 'unknown')
        cost = record.get('cost_usd', 0.0)
        model = record.get('model', 'unknown')

        summary_parts.append(f"\n{stage.upper()}:")
        summary_parts.append(f"  Timestamp: {timestamp}")
        summary_parts.append(f"  Model: {model}")
        summary_parts.append(f"  Cost: ${cost:.4f}")

        if 'pages_processed' in record:
            summary_parts.append(f"  Pages: {record['pages_processed']}")

        total_cost += cost

    summary_parts.append(f"\n{'=' * 60}")
    summary_parts.append(f"Total Cost: ${total_cost:.4f}")

    return "\n".join(summary_parts)
