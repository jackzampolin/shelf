from flask import Blueprint, render_template, send_file, abort, jsonify, redirect, url_for

from web.config import Config
from infra.pipeline.storage.library import Library
from web.data.extract_toc_data import get_extract_toc_data, get_validation_data
from web.data.find_toc_data import get_toc_page_numbers
from web.data.label_pages_data import get_label_pages_report, get_page_labels
from web.data.label_structure_data import (
    get_label_structure_report,
    get_page_labels as get_structure_page_labels
)
from web.data.link_toc_data import get_link_toc_data, get_linked_entries_tree
from web.data.ocr_pages_data import (
    get_ocr_pages_data, get_page_ocr_text, get_blend_text
)
from web.data.common_structure_data import (
    get_structure_summary, get_structure_entries, get_entry_detail
)

stage_bp = Blueprint('stage', __name__)


@stage_bp.route('/stage/<scan_id>/ocr-pages')
def ocr_pages_redirect(scan_id: str):
    return redirect(f'/stage/{scan_id}/ocr-pages/1')


@stage_bp.route('/stage/<scan_id>/ocr-pages/<int:page_num>')
def ocr_pages_view(scan_id: str, page_num: int):
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    ocr_data = get_ocr_pages_data(storage)

    if not ocr_data:
        abort(404, f"No OCR stages run for '{scan_id}'")

    min_page, max_page = ocr_data['page_range']
    page_num = max(min_page, min(page_num, max_page))

    return render_template(
        'stage/ocr_pages.html',
        scan_id=scan_id,
        metadata=metadata,
        ocr_data=ocr_data,
        initial_page=page_num,
    )


@stage_bp.route('/api/blend/<scan_id>/<int:page_num>')
def api_get_blend_text(scan_id: str, page_num: int):
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    if not library.get_scan_info(scan_id):
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    text = get_blend_text(storage, page_num)

    if text is None:
        abort(404, f"No blend data for page {page_num}")

    return jsonify({"text": text})


@stage_bp.route('/stage/<scan_id>/extract-toc')
def extract_toc_view(scan_id: str):
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    toc_data = get_extract_toc_data(storage)

    if not toc_data:
        abort(404, f"Extract-toc stage not run for '{scan_id}'")

    validation_data = get_validation_data(storage)
    page_numbers = get_toc_page_numbers(storage)

    return render_template(
        'stage/extract_toc.html',
        scan_id=scan_id,
        metadata=metadata,
        toc_data=toc_data,
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
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    report = get_label_structure_report(storage)

    if not report:
        abort(404, f"Label-structure stage not run for '{scan_id}'")

    stage_storage = storage.stage("label-structure")
    clusters_path = stage_storage.output_dir / "gap_analysis" / "clusters.json"
    has_clusters = clusters_path.exists()

    return render_template(
        'stage/label_structure.html',
        scan_id=scan_id,
        metadata=metadata,
        report=report,
        has_clusters=has_clusters,
    )


@stage_bp.route('/stage/<scan_id>/label-structure/page/<int:page_num>')
def label_structure_page_view(scan_id: str, page_num: int):
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    labels = get_structure_page_labels(storage, page_num)

    if not labels:
        abort(404, f"Page {page_num} not found in label-structure report")

    return render_template(
        'stage/label_structure_page.html',
        scan_id=scan_id,
        metadata=metadata,
        page_num=page_num,
        labels=labels,
    )


@stage_bp.route('/stage/<scan_id>/label-structure/clusters')
def label_structure_clusters_view(scan_id: str):
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    stage_storage = storage.stage("label-structure")
    clusters_path = stage_storage.output_dir / "gap_analysis" / "clusters.json"

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
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    if not library.get_scan_info(scan_id):
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    text = get_page_ocr_text(storage, provider, page_num)

    if text is None:
        abort(404, f"No OCR data for page {page_num} from {provider}")

    return jsonify({"text": text})


@stage_bp.route('/image/<scan_id>/source/<int:page_num>')
def serve_source_image(scan_id: str, page_num: int):
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    if not library.get_scan_info(scan_id):
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)
    source_dir = storage.book_dir / "source"
    image_filename = f"page_{page_num:04d}.png"
    image_path = source_dir / image_filename

    if not image_path.exists():
        abort(404, f"Page image not found: {image_filename}")

    return send_file(str(image_path), mimetype='image/png')


@stage_bp.route('/stage/<scan_id>/common-structure')
def common_structure_view(scan_id: str):
    """
    Common-structure stage view.

    Shows:
    - Summary stats (entries, chapters, word counts)
    - List of all structure entries with text preview
    - Click entry to see full text content
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    summary = get_structure_summary(storage)
    if not summary:
        abort(404, f"Common-structure stage not run for '{scan_id}'")

    entries = get_structure_entries(storage)

    return render_template(
        'stage/common_structure.html',
        scan_id=scan_id,
        metadata=metadata,
        summary=summary,
        entries=entries,
    )


@stage_bp.route('/stage/<scan_id>/common-structure/entry/<entry_id>')
def common_structure_entry_view(scan_id: str, entry_id: str):
    """
    Individual entry view for common-structure.

    Shows:
    - Full final text
    - Edits applied
    - Per-page breakdown
    - Page images on the side
    """
    library = Library(storage_root=Config.BOOK_STORAGE_ROOT)

    metadata = library.get_scan_info(scan_id)
    if not metadata:
        abort(404, f"Book '{scan_id}' not found")

    storage = library.get_book_storage(scan_id)

    entry = get_entry_detail(storage, entry_id)
    if not entry:
        abort(404, f"Entry '{entry_id}' not found")

    # Get all entries for navigation
    all_entries = get_structure_entries(storage)

    # Find prev/next
    entry_ids = [e['entry_id'] for e in all_entries]
    current_idx = entry_ids.index(entry_id) if entry_id in entry_ids else -1
    prev_entry = entry_ids[current_idx - 1] if current_idx > 0 else None
    next_entry = entry_ids[current_idx + 1] if current_idx < len(entry_ids) - 1 else None

    return render_template(
        'stage/common_structure_entry.html',
        scan_id=scan_id,
        metadata=metadata,
        entry=entry,
        all_entries=all_entries,
        prev_entry=prev_entry,
        next_entry=next_entry,
    )
