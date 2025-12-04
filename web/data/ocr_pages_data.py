from typing import Dict, Any, Optional
import json

from infra.pipeline.storage.book_storage import BookStorage
from web.data.status_reader import get_stage_status_from_disk


OCR_PROVIDERS = ['olm-ocr', 'mistral-ocr', 'paddle-ocr']
PROVIDER_SUBDIRS = {
    'olm-ocr': 'olm',
    'mistral-ocr': 'mistral',
    'paddle-ocr': 'paddle',
}


def get_ocr_aggregate_status(storage: BookStorage) -> Dict[str, Any]:
    aggregate = {
        'status': 'not_started',
        'providers': {},
        'total_cost_usd': 0.0,
        'total_runtime_seconds': 0.0,
        'total_pages_processed': 0
    }

    stage_status = get_stage_status_from_disk(storage, 'ocr-pages')
    stage_storage = storage.stage('ocr-pages')

    source_dir = storage.book_dir / "source"
    total_pages = len(list(source_dir.glob("page_*.png"))) if source_dir.exists() else 0

    completed_count = 0
    in_progress_count = 0
    not_started_count = 0

    for provider in OCR_PROVIDERS:
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

    if completed_count == len(OCR_PROVIDERS):
        aggregate['status'] = 'completed'
    elif completed_count > 0 or in_progress_count > 0:
        aggregate['status'] = 'in_progress'
    else:
        aggregate['status'] = 'not_started'

    return aggregate


def get_ocr_pages_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
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

    return {
        'providers': OCR_PROVIDERS,
        'page_range': page_range,
        'provider_data': aggregate['providers']
    }


def get_page_ocr_text(storage: BookStorage, provider: str, page_num: int) -> Optional[str]:
    if provider not in OCR_PROVIDERS:
        return None

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
