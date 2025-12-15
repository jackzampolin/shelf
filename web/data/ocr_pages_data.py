from typing import Dict, Any, Optional, List
import json

from infra.pipeline.storage.book_storage import BookStorage
from web.data.status_reader import get_stage_status_from_disk


# Default providers (used when we can't detect from disk)
DEFAULT_OCR_PROVIDERS = ['mistral-ocr', 'paddle-ocr']

# Map from provider name to output subdirectory
PROVIDER_SUBDIRS = {
    'olm-ocr': 'olm',
    'mistral-ocr': 'mistral',
    'paddle-ocr': 'paddle',
}


def get_active_providers(storage: BookStorage) -> List[str]:
    """Detect which OCR providers have output directories."""
    stage_storage = storage.stage('ocr-pages')
    if not stage_storage.output_dir.exists():
        return DEFAULT_OCR_PROVIDERS

    active = []
    for provider, subdir in PROVIDER_SUBDIRS.items():
        provider_dir = stage_storage.output_dir / subdir
        if provider_dir.exists() and list(provider_dir.glob("page_*.json")):
            active.append(provider)

    return active if active else DEFAULT_OCR_PROVIDERS


def get_ocr_aggregate_status(storage: BookStorage) -> Dict[str, Any]:
    """Get aggregate status for OCR providers and phases."""
    aggregate = {
        'status': 'not_started',
        'providers': {},
        'phases': {},
        'total_cost_usd': 0.0,
        'total_runtime_seconds': 0.0,
        'total_pages_processed': 0
    }

    stage_status = get_stage_status_from_disk(storage, 'ocr-pages')
    stage_storage = storage.stage('ocr-pages')

    source_dir = storage.book_dir / "source"
    total_pages = len(list(source_dir.glob("page_*.png"))) if source_dir.exists() else 0

    # Get active providers
    active_providers = get_active_providers(storage)

    completed_count = 0
    in_progress_count = 0
    not_started_count = 0

    for provider in active_providers:
        subdir = PROVIDER_SUBDIRS.get(provider)
        provider_dir = stage_storage.output_dir / subdir if subdir else None

        if provider_dir and provider_dir.exists():
            pages_processed = len(list(provider_dir.glob("page_*.json")))

            if pages_processed >= total_pages and total_pages > 0:
                provider_status = 'completed'
                completed_count += 1
            elif pages_processed > 0:
                provider_status = 'in_progress'
                in_progress_count += 1
            else:
                provider_status = 'not_started'
                not_started_count += 1

            aggregate['providers'][provider] = {
                'status': provider_status,
                'cost_usd': 0.0,
                'runtime_seconds': 0.0,
                'pages_processed': pages_processed
            }

            aggregate['total_pages_processed'] = max(
                aggregate['total_pages_processed'],
                pages_processed
            )
        else:
            aggregate['providers'][provider] = {
                'status': 'not_started',
                'cost_usd': 0.0,
                'runtime_seconds': 0.0,
                'pages_processed': 0
            }
            not_started_count += 1

    if stage_status:
        metrics = stage_status.get('metrics', {})
        aggregate['total_cost_usd'] = metrics.get('total_cost_usd', 0.0)
        aggregate['total_runtime_seconds'] = metrics.get('stage_runtime_seconds', 0.0)

    # Determine OCR phase status
    if completed_count == len(active_providers) and len(active_providers) > 0:
        ocr_status = 'completed'
    elif completed_count > 0 or in_progress_count > 0:
        ocr_status = 'in_progress'
    else:
        ocr_status = 'not_started'

    # Check blend phase status
    blend_dir = stage_storage.output_dir / "blend"
    blend_pages = len(list(blend_dir.glob("page_*.json"))) if blend_dir.exists() else 0
    if blend_pages >= total_pages and total_pages > 0:
        blend_status = 'completed'
    elif blend_pages > 0:
        blend_status = 'in_progress'
    else:
        blend_status = 'not_started'

    # Check metadata phase status (marker file at stage output_dir level)
    metadata_marker = stage_storage.output_dir / "metadata_extracted.json"
    if metadata_marker.exists():
        metadata_status = 'completed'
    else:
        metadata_status = 'not_started'

    # Add phase status
    aggregate['phases'] = {
        'ocr': {'status': ocr_status, 'pages_processed': aggregate['total_pages_processed'], 'total_pages': total_pages},
        'blend': {'status': blend_status, 'pages_processed': blend_pages, 'total_pages': total_pages},
        'metadata': {'status': metadata_status},
    }

    # Overall status based on all phases
    if metadata_status == 'completed':
        aggregate['status'] = 'completed'
    elif blend_status == 'completed' or blend_status == 'in_progress':
        aggregate['status'] = 'in_progress_blend'
    elif ocr_status == 'completed' or ocr_status == 'in_progress':
        aggregate['status'] = 'in_progress_ocr'
    else:
        aggregate['status'] = 'not_started'

    return aggregate


def get_ocr_pages_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """Get OCR pages data for web UI including providers and phases."""
    aggregate = get_ocr_aggregate_status(storage)

    if aggregate['status'] == 'not_started':
        return None

    source_dir = storage.book_dir / "source"
    if source_dir.exists():
        page_files = sorted(source_dir.glob("page_*.png"))
        if page_files:
            first_page = int(page_files[0].stem.split('_')[1])
            last_page = int(page_files[-1].stem.split('_')[1])
            page_range = (first_page, last_page)
        else:
            page_range = (1, 1)
    else:
        page_range = (1, 1)

    # Get active providers dynamically
    active_providers = get_active_providers(storage)

    return {
        'providers': active_providers,
        'page_range': page_range,
        'provider_data': aggregate['providers'],
        'phases': aggregate['phases'],
        'status': aggregate['status'],
        'total_cost_usd': aggregate['total_cost_usd'],
        'total_runtime_seconds': aggregate['total_runtime_seconds'],
    }


def get_page_ocr_text(storage: BookStorage, provider: str, page_num: int) -> Optional[str]:
    """Get OCR text for a specific page from a specific provider."""
    subdir = PROVIDER_SUBDIRS.get(provider)
    if not subdir:
        return None

    stage_storage = storage.stage('ocr-pages')
    page_file = stage_storage.output_dir / subdir / f"page_{page_num:04d}.json"

    if not page_file.exists():
        return None

    try:
        with open(page_file, 'r') as f:
            data = json.load(f)

            if provider == 'mistral-ocr':
                return data.get('markdown', '')
            elif provider in ['olm-ocr', 'paddle-ocr']:
                return data.get('text', '')

            for key in ['text', 'markdown', 'content', 'ocr_text', 'result']:
                if key in data:
                    return data[key]

            return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error reading OCR data: {str(e)}"


def get_blend_text(storage: BookStorage, page_num: int) -> Optional[str]:
    """Get blended text for a specific page."""
    stage_storage = storage.stage("ocr-pages")
    page_file = stage_storage.output_dir / "blend" / f"page_{page_num:04d}.json"

    if not page_file.exists():
        return None

    try:
        with open(page_file, 'r') as f:
            data = json.load(f)
            return data.get('markdown', '')
    except Exception:
        return None


def get_metadata_status(storage: BookStorage) -> Optional[Dict[str, Any]]:
    """Get metadata extraction status and results."""
    stage_storage = storage.stage("ocr-pages")

    # Check for marker file (indicates extraction completed)
    marker_file = stage_storage.output_dir / "metadata_extracted.json"
    if not marker_file.exists():
        return None

    try:
        with open(marker_file, 'r') as f:
            marker_data = json.load(f)
    except Exception:
        marker_data = {}

    # Load full metadata from book's metadata.json
    metadata_file = storage.metadata_file
    full_metadata = {}
    if metadata_file.exists():
        try:
            with open(metadata_file, 'r') as f:
                full_metadata = json.load(f)
        except Exception:
            pass

    return {
        'status': marker_data.get('status', 'completed'),
        'title': marker_data.get('title') or full_metadata.get('title', 'Unknown'),
        'authors': marker_data.get('authors') or full_metadata.get('authors', []),
        'isbn': marker_data.get('isbn') or full_metadata.get('identifiers', {}).get('isbn_13') or full_metadata.get('identifiers', {}).get('isbn_10'),
        'confidence': marker_data.get('confidence', 0.0),
        'full_metadata': full_metadata,
    }
