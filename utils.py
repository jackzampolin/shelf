"""
Utility functions for AR Research pipeline.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any


def update_book_metadata(book_dir: Path, stage: str, metadata: Dict[str, Any]):
    """
    Update book metadata.json with processing information.

    Args:
        book_dir: Path to book directory
        stage: Pipeline stage name (ocr, correct, fix, structure)
        metadata: Dictionary of metadata to add for this stage
    """
    metadata_file = book_dir / "metadata.json"

    # Load existing metadata
    if metadata_file.exists():
        with open(metadata_file, 'r') as f:
            book_metadata = json.load(f)
    else:
        book_metadata = {}

    # Ensure processing_history exists
    if 'processing_history' not in book_metadata:
        book_metadata['processing_history'] = []

    # Add new processing record
    processing_record = {
        'stage': stage,
        'timestamp': datetime.now().isoformat(),
        **metadata
    }

    book_metadata['processing_history'].append(processing_record)

    # Also update stage-specific top-level keys for backwards compatibility
    if stage == 'ocr':
        book_metadata['ocr_complete'] = True
        book_metadata['ocr_completion_date'] = datetime.now().isoformat()
        if 'pages_processed' in metadata:
            book_metadata['total_pages_processed'] = metadata['pages_processed']

    # Save updated metadata
    with open(metadata_file, 'w') as f:
        json.dump(book_metadata, f, indent=2)


def get_latest_processing_record(book_dir: Path, stage: str) -> Dict[str, Any]:
    """
    Get the most recent processing record for a stage.

    Args:
        book_dir: Path to book directory
        stage: Pipeline stage name

    Returns:
        Dictionary of processing metadata, or None if not found
    """
    metadata_file = book_dir / "metadata.json"

    if not metadata_file.exists():
        return None

    with open(metadata_file, 'r') as f:
        book_metadata = json.load(f)

    processing_history = book_metadata.get('processing_history', [])

    # Get most recent record for this stage
    stage_records = [r for r in processing_history if r['stage'] == stage]

    return stage_records[-1] if stage_records else None


def get_scan_total_cost(book_dir: Path) -> float:
    """
    Calculate total cost for a scan from processing history.

    Args:
        book_dir: Path to book directory

    Returns:
        Total cost in USD
    """
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
    """
    Get models used for each stage from processing history.

    Args:
        book_dir: Path to book directory

    Returns:
        Dictionary mapping stage names to model names
    """
    metadata_file = book_dir / "metadata.json"

    if not metadata_file.exists():
        return {}

    with open(metadata_file, 'r') as f:
        book_metadata = json.load(f)

    processing_history = book_metadata.get('processing_history', [])

    # Get most recent model for each stage
    models = {}
    for record in processing_history:
        stage = record.get('stage')
        model = record.get('model')
        if stage and model:
            models[stage] = model

    return models


def format_processing_summary(book_dir: Path) -> str:
    """
    Generate a human-readable processing summary from metadata.

    Args:
        book_dir: Path to book directory

    Returns:
        Formatted string with processing summary
    """
    metadata_file = book_dir / "metadata.json"

    if not metadata_file.exists():
        return "No metadata found"

    with open(metadata_file, 'r') as f:
        book_metadata = json.load(f)

    title = book_metadata.get('title', 'Unknown')
    author = book_metadata.get('author', 'Unknown')

    lines = [
        f"📖 {title}",
        f"   By {author}",
        ""
    ]

    processing_history = book_metadata.get('processing_history', [])

    if not processing_history:
        lines.append("No processing history found")
        return "\n".join(lines)

    # Group by stage
    stage_records = {}
    for record in processing_history:
        stage = record['stage']
        if stage not in stage_records:
            stage_records[stage] = []
        stage_records[stage].append(record)

    # Print each stage
    for stage in ['ocr', 'correct', 'fix', 'structure']:
        if stage not in stage_records:
            continue

        records = stage_records[stage]
        latest = records[-1]

        lines.append(f"✅ {stage.upper()}")
        lines.append(f"   Model: {latest.get('model', 'N/A')}")
        lines.append(f"   Date: {latest.get('timestamp', 'N/A')[:10]}")

        # Stage-specific details
        if stage == 'ocr':
            lines.append(f"   Pages: {latest.get('pages_processed', 0)}")
            lines.append(f"   Cost: $0.00 (free)")

        elif stage == 'correct':
            lines.append(f"   Pages: {latest.get('pages_processed', 0)}")
            lines.append(f"   Errors: {latest.get('total_errors_found', 0)}")
            lines.append(f"   Cost: ${latest.get('cost_usd', 0):.2f}")

        elif stage == 'fix':
            lines.append(f"   Pages Fixed: {latest.get('pages_fixed', 0)}")
            lines.append(f"   Cost: ${latest.get('cost_usd', 0):.2f}")

        elif stage == 'structure':
            lines.append(f"   Chapters: {latest.get('chapters_detected', 0)}")
            lines.append(f"   Chunks: {latest.get('chunks_created', 0)}")
            lines.append(f"   Cost: ${latest.get('cost_usd', 0):.2f}")

        lines.append("")

    # Total cost
    total_cost = get_scan_total_cost(book_dir)
    lines.append(f"💰 Total Cost: ${total_cost:.2f}")

    return "\n".join(lines)
