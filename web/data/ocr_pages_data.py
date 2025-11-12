"""
OCR pages data access functions.

Provides data for multi-provider OCR stage view.
Ground truth from disk (ADR 001).
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
import json

from infra.pipeline.storage.book_storage import BookStorage
from web.data.status_reader import get_stage_status_from_disk


OCR_PROVIDERS = ['olm-ocr', 'mistral-ocr', 'paddle-ocr']


def get_ocr_aggregate_status(storage: BookStorage) -> Dict[str, Any]:
    """
    Get aggregate status for all OCR providers.

    Returns:
        {
            'status': 'completed' | 'in_progress' | 'not_started',
            'providers': {
                'olm-ocr': {'status': '...', 'cost_usd': 0.0, 'runtime_seconds': 0.0, 'pages_processed': 0},
                'mistral-ocr': {...},
                'paddle-ocr': {...}
            },
            'total_cost_usd': 0.0,
            'total_runtime_seconds': 0.0,
            'total_pages_processed': 0
        }
    """
    aggregate = {
        'status': 'not_started',
        'providers': {},
        'total_cost_usd': 0.0,
        'total_runtime_seconds': 0.0,
        'total_pages_processed': 0
    }

    completed_count = 0
    in_progress_count = 0
    not_started_count = 0

    for provider in OCR_PROVIDERS:
        status = get_stage_status_from_disk(storage, provider)

        if status:
            provider_status = status.get('status', 'not_started')
            metrics = status.get('metrics', {})

            provider_data = {
                'status': provider_status,
                'cost_usd': metrics.get('total_cost_usd', 0.0),
                'runtime_seconds': metrics.get('stage_runtime_seconds', 0.0),
                'pages_processed': metrics.get('pages_processed', 0)
            }

            aggregate['providers'][provider] = provider_data
            aggregate['total_cost_usd'] += provider_data['cost_usd']
            aggregate['total_runtime_seconds'] += provider_data['runtime_seconds']
            aggregate['total_pages_processed'] = max(
                aggregate['total_pages_processed'],
                provider_data['pages_processed']
            )

            if provider_status == 'completed':
                completed_count += 1
            elif provider_status == 'in_progress':
                in_progress_count += 1
            else:
                not_started_count += 1
        else:
            aggregate['providers'][provider] = {
                'status': 'not_started',
                'cost_usd': 0.0,
                'runtime_seconds': 0.0,
                'pages_processed': 0
            }
            not_started_count += 1

    # Determine aggregate status:
    # - All completed → 'completed'
    # - Any in progress or mix of completed/not_started → 'in_progress'
    # - All not started → 'not_started'
    if completed_count == len(OCR_PROVIDERS):
        aggregate['status'] = 'completed'
    elif completed_count > 0 or in_progress_count > 0:
        aggregate['status'] = 'in_progress'
    else:
        aggregate['status'] = 'not_started'

    return aggregate


def get_ocr_pages_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """
    Get OCR pages data for all providers.

    Returns:
        {
            'providers': ['olm-ocr', 'mistral-ocr', 'paddle-ocr'],
            'page_range': (1, 300),  # Total page range
            'provider_data': {
                'olm-ocr': {'status': '...', 'cost_usd': 0.0, ...},
                'mistral-ocr': {...},
                'paddle-ocr': {...}
            }
        }
    """
    aggregate = get_ocr_aggregate_status(storage)

    if aggregate['status'] == 'not_started':
        return None

    # Get page range from source directory
    source_dir = storage.book_dir / "source"
    if source_dir.exists():
        page_files = sorted(source_dir.glob("page_*.png"))
        if page_files:
            # Extract page numbers from filenames (page_0001.png -> 1)
            first_page = int(page_files[0].stem.split('_')[1])
            last_page = int(page_files[-1].stem.split('_')[1])
            page_range = (first_page, last_page)
        else:
            page_range = (1, 1)
    else:
        page_range = (1, 1)

    return {
        'providers': OCR_PROVIDERS,
        'page_range': page_range,
        'provider_data': aggregate['providers']
    }


def get_page_ocr_text(storage: BookStorage, provider: str, page_num: int) -> Optional[str]:
    """
    Get OCR text for a specific page from a specific provider.

    Args:
        storage: BookStorage instance
        provider: Provider name (olm-ocr, mistral-ocr, paddle-ocr)
        page_num: Page number (1-indexed)

    Returns:
        OCR text string or None if not found
    """
    if provider not in OCR_PROVIDERS:
        return None

    stage_storage = storage.stage(provider)
    page_file = stage_storage.output_dir / f"page_{page_num:04d}.json"

    if not page_file.exists():
        return None

    try:
        with open(page_file, 'r') as f:
            data = json.load(f)

            # Provider-specific field names
            if provider == 'mistral-ocr':
                return data.get('markdown', '')
            elif provider in ['olm-ocr', 'paddle-ocr']:
                return data.get('text', '')

            # Fallback: try common keys
            for key in ['text', 'markdown', 'content', 'ocr_text', 'result']:
                if key in data:
                    return data[key]

            # If no standard key, return the whole JSON pretty-printed
            return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error reading OCR data: {str(e)}"


def get_all_providers_text(storage: BookStorage, page_num: int) -> Dict[str, Optional[str]]:
    """
    Get OCR text from all providers for a specific page.

    Args:
        storage: BookStorage instance
        page_num: Page number (1-indexed)

    Returns:
        Dict mapping provider name to OCR text (or None if not available)
    """
    return {
        provider: get_page_ocr_text(storage, provider, page_num)
        for provider in OCR_PROVIDERS
    }
