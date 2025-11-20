"""
Stage detail view routes.

Provides views for individual stage outputs:
- /stage/<scan_id>/<stage_name> - Stage detail view
- /image/<scan_id>/source/<page_num> - Serve source page image
"""

from flask import Blueprint, render_template, send_file, abort, jsonify
from pathlib import Path

from web.config import Config
from infra.pipeline.storage.library import Library
from web.data.extract_toc_data import get_extract_toc_data, get_validation_data
from web.data.find_toc_data import get_find_toc_data, get_toc_page_numbers
from web.data.label_pages_data import get_label_pages_report, get_page_labels
from web.data.label_structure_data import (
    get_label_structure_report,
    get_page_labels as get_structure_page_labels
)
from web.data.link_toc_data import get_link_toc_data, get_linked_entries_tree
from web.data.ocr_pages_data import get_ocr_pages_data, get_all_providers_text, get_page_ocr_text

stage_bp = Blueprint('stage', __name__)


@stage_bp.route('/stage/<scan_id>/ocr-pages')
def ocr_pages_view(scan_id: str):
    """
    OCR pages stage detail view.

    Shows aggregate status for all OCR providers with links to individual pages.
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Get book metadata
    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    # Load OCR data from disk
    ocr_data = get_ocr_pages_data(storage)

    if not ocr_data:
        abort(404, f"No OCR stages run for '{scan_id}'")

    return render_template(
        'stage/ocr_pages.html',
        scan_id=scan_id,
        metadata=metadata,
        ocr_data=ocr_data,
    )


@stage_bp.route('/stage/<scan_id>/ocr-pages/page/<int:page_num>')
def ocr_pages_page_view(scan_id: str, page_num: int):
    """
    Individual page view for OCR pages stage.

    Shows:
    - Page image on left
    - Tabbed view of OCR text from each provider on right
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Get book metadata
    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    # Get OCR text from all providers
    provider_texts = get_all_providers_text(storage, page_num)

    # Check if any provider has data for this page
    if not any(text is not None for text in provider_texts.values()):
        abort(404, f"No OCR data found for page {page_num}")

    return render_template(
        'stage/ocr_pages_page.html',
        scan_id=scan_id,
        metadata=metadata,
        page_num=page_num,
        provider_texts=provider_texts,
    )


@stage_bp.route('/stage/<scan_id>/extract-toc')
def extract_toc_view(scan_id: str):
    """
    Extract-toc stage detail view.

    Shows:
    - TOC page images on the left (from find phase)
    - Finder analysis (confidence, reasoning, structure summary)
    - Parsed TOC structure (from extract phase)
    - Validation analysis (from validate phase)
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Get book metadata (returns None if book doesn't exist)
    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    # Load extract-toc data from disk
    toc_data = get_extract_toc_data(storage)

    if not toc_data:
        abort(404, f"Extract-toc stage not run for '{scan_id}'")

    # Load finder data (from find phase)
    finder_data = get_find_toc_data(storage)

    # Load validation data (corrections and analysis)
    validation_data = get_validation_data(storage)

    # Get page numbers for images (from find phase)
    page_numbers = get_toc_page_numbers(storage)

    return render_template(
        'stage/extract_toc.html',
        scan_id=scan_id,
        metadata=metadata,
        toc_data=toc_data,
        finder_data=finder_data,
        validation_data=validation_data,
        page_numbers=page_numbers,
    )


@stage_bp.route('/stage/<scan_id>/link-toc')
def link_toc_view(scan_id: str):
    """
    Link-toc stage detail view with progressive enhancement.

    Shows:
    - Enriched ToC (Phase 4) if available, or linked ToC (Phase 1) as fallback
    - Discovered headings highlighted with "✨ Discovered" badge
    - Expandable sections: Pattern Analysis (Phase 2) and Evaluation Details (Phase 3)
    - Clickable ToC sidebar with page viewer on the right
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Get book metadata
    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    # Load link-toc data from disk
    toc_data = get_link_toc_data(storage)

    if not toc_data:
        abort(404, f"Link-toc stage not run for '{scan_id}'")

    # Get linked entries
    entries = get_linked_entries_tree(storage)

    return render_template(
        'stage/link_toc.html',
        scan_id=scan_id,
        metadata=metadata,
        toc_data=toc_data,
        entries=entries,
    )


@stage_bp.route('/stage/<scan_id>/label-pages')
def label_pages_view(scan_id: str):
    """
    Label-pages stage detail view.

    Shows:
    - Report table with all page labels
    - Links to individual page viewers
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Get book metadata
    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    # Load label-pages report from disk
    report = get_label_pages_report(storage)

    if not report:
        abort(404, f"Label-pages stage not run for '{scan_id}'")

    return render_template(
        'stage/label_pages.html',
        scan_id=scan_id,
        metadata=metadata,
        report=report,
    )


@stage_bp.route('/stage/<scan_id>/label-pages/page/<int:page_num>')
def label_pages_page_view(scan_id: str, page_num: int):
    """
    Individual page view for label-pages stage.

    Shows:
    - Page image on left
    - Page labels on right in human-readable format
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Get book metadata
    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    # Get labels for this page
    labels = get_page_labels(storage, page_num)

    if not labels:
        abort(404, f"Page {page_num} not found in label-pages report")

    return render_template(
        'stage/label_pages_page.html',
        scan_id=scan_id,
        metadata=metadata,
        page_num=page_num,
        labels=labels,
    )


@stage_bp.route('/stage/<scan_id>/label-structure')
def label_structure_view(scan_id: str):
    from flask import request

    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    report_type = request.args.get('report', 'full')
    if report_type not in ['base', 'simple', 'full']:
        report_type = 'full'

    report = get_label_structure_report(storage, report_type)

    if not report:
        abort(404, f"Label-structure stage not run for '{scan_id}'")

    stage_storage = storage.stage("label-structure")
    clusters_path = stage_storage.output_dir / "clusters" / "clusters.json"
    has_clusters = clusters_path.exists()

    return render_template(
        'stage/label_structure.html',
        scan_id=scan_id,
        metadata=metadata,
        report=report,
        has_clusters=has_clusters,
        current_report=report_type,
    )


@stage_bp.route('/stage/<scan_id>/label-structure/page/<int:page_num>')
def label_structure_page_view(scan_id: str, page_num: int):
    from flask import request

    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    report_type = request.args.get('report', 'full')
    if report_type not in ['base', 'simple', 'full']:
        report_type = 'full'

    labels = get_structure_page_labels(storage, page_num, report_type)

    if not labels:
        abort(404, f"Page {page_num} not found in label-structure report")

    return render_template(
        'stage/label_structure_page.html',
        scan_id=scan_id,
        metadata=metadata,
        page_num=page_num,
        labels=labels,
        current_report=report_type,
    )


@stage_bp.route('/stage/<scan_id>/label-structure/clusters')
def label_structure_clusters_view(scan_id: str):
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    stage_storage = storage.stage("label-structure")
    clusters_path = stage_storage.output_dir / "clusters" / "clusters.json"

    if not clusters_path.exists():
        abort(404, f"Clusters not found for '{scan_id}'")

    import json
    with open(clusters_path, 'r') as f:
        clusters_data = json.load(f)

    return render_template(
        'stage/label_structure_clusters.html',
        scan_id=scan_id,
        metadata=metadata,
        clusters_data=clusters_data,
    )


@stage_bp.route('/api/ocr/<scan_id>/<provider>/<int:page_num>')
def api_get_ocr_text(scan_id: str, provider: str, page_num: int):
    """
    API endpoint to get OCR text for a specific page from a specific provider.

    Returns JSON: {"text": "..."}
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Check book exists
    if not library.get_scan_info(scan_id):
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    # Get OCR text
    text = get_page_ocr_text(storage, provider, page_num)

    if text is None:
        abort(404, f"No OCR data for page {page_num} from {provider}")

    return jsonify({"text": text})


@stage_bp.route('/image/<scan_id>/source/<int:page_num>')
def serve_source_image(scan_id: str, page_num: int):
    """
    Serve source page image.

    Returns PNG image from source/ directory.
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    # Check book exists
    if not library.get_scan_info(scan_id):
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    source_dir = storage.book_dir / "source"

    # Format page number: page_0001.png
    image_filename = f"page_{page_num:04d}.png"
    image_path = source_dir / image_filename

    if not image_path.exists():
        abort(404, f"Page image not found: {image_filename}")

    return send_file(str(image_path), mimetype='image/png')
