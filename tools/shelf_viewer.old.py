#!/usr/bin/env python3
"""
Shelf Viewer - Unified Flask app for debugging book processing pipeline.

Tools:
- ToC Viewer: View parsed table of contents with page images
- Correction Viewer: Compare OCR output with corrections
- Label Viewer: View page labels with visual overlays
- Stats Viewer: View book-level label statistics

Usage:
    python tools/shelf_viewer.py [--port 5000] [--host 127.0.0.1]
"""

import csv
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from flask import Flask, render_template_string, send_file, abort, request

app = Flask(__name__)

# Get library root from env or default
LIBRARY_ROOT = Path(os.getenv("BOOK_STORAGE_ROOT", "~/Documents/book_scans")).expanduser()


# ============================================================================
# Shared Utilities
# ============================================================================

def find_all_books() -> List[Dict[str, Any]]:
    """Find all books in library with their available stages."""
    books = []
    for book_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith('.'):
            continue

        book_info = {
            "scan_id": book_dir.name,
            "has_source": (book_dir / "source").exists(),
            "has_ocr": (book_dir / "ocr").exists(),
            "has_corrections": (book_dir / "corrections").exists(),
            "has_labels": (book_dir / "labels").exists(),
            "has_merged": (book_dir / "merged").exists(),
            "has_toc": (book_dir / "build_structure" / "toc.json").exists(),
        }

        # Check if ToC has actual data
        if book_info["has_toc"]:
            toc_path = book_dir / "build_structure" / "toc.json"
            with open(toc_path) as f:
                toc_data = json.load(f)
            if "note" in toc_data and "No ToC found" in toc_data["note"]:
                book_info["has_toc"] = False

        books.append(book_info)

    return books


def get_page_image_path(scan_id: str, page_num: int) -> Optional[Path]:
    """Get path to source image for a page."""
    # Check for PNG first
    img_path = LIBRARY_ROOT / scan_id / "source" / f"page_{page_num:04d}.png"
    if img_path.exists():
        return img_path
    # Try JPG
    img_path = LIBRARY_ROOT / scan_id / "source" / f"page_{page_num:04d}.jpg"
    if img_path.exists():
        return img_path
    return None


def get_stage_data(scan_id: str, stage: str, page_num: int) -> Optional[Dict]:
    """Load JSON data for a specific stage and page."""
    data_path = LIBRARY_ROOT / scan_id / stage / f"page_{page_num:04d}.json"
    if not data_path.exists():
        return None
    with open(data_path) as f:
        return json.load(f)


def get_book_pages(scan_id: str) -> List[int]:
    """Get list of page numbers for a book."""
    source_dir = LIBRARY_ROOT / scan_id / "source"
    if not source_dir.exists():
        return []

    pages = []
    for img_path in sorted(source_dir.glob("page_*.png")) or sorted(source_dir.glob("page_*.jpg")):
        page_num = int(img_path.stem.split('_')[1])
        pages.append(page_num)
    return sorted(pages)


# ============================================================================
# Base Template (shared header/navigation)
# ============================================================================

def render_page(title: str, active_page: str, extra_styles: str, content: str) -> str:
    """Render a complete page with navigation."""
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f5f5;
        }}
        .navbar {{
            background: #2c3e50;
            color: white;
            padding: 15px 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .navbar h1 {{
            font-size: 1.5em;
            margin-bottom: 10px;
        }}
        .navbar nav a {{
            color: #3498db;
            text-decoration: none;
            margin-right: 20px;
            font-size: 0.9em;
        }}
        .navbar nav a:hover {{
            color: #5dade2;
            text-decoration: underline;
        }}
        .navbar nav a.active {{
            color: #5dade2;
            font-weight: 600;
        }}
        {extra_styles}
    </style>
</head>
<body>
    <div class="navbar">
        <h1>📚 Shelf Viewer</h1>
        <nav>
            <a href="/" {'class="active"' if active_page == 'home' else ''}>Home</a>
            <a href="/toc" {'class="active"' if active_page == 'toc' else ''}>ToC Viewer</a>
            <a href="/corrections" {'class="active"' if active_page == 'corrections' else ''}>Corrections</a>
            <a href="/labels" {'class="active"' if active_page == 'labels' else ''}>Labels</a>
            <a href="/stats" {'class="active"' if active_page == 'stats' else ''}>Stats</a>
        </nav>
    </div>
    {content}
</body>
</html>
"""


# ============================================================================
# Home Page
# ============================================================================

HOME_PAGE_STYLES = """
.container {
    max-width: 1200px;
    margin: 40px auto;
    padding: 0 20px;
}
.intro {
    background: white;
    padding: 30px;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    margin-bottom: 30px;
}
.intro h2 {
    color: #2c3e50;
    margin-bottom: 15px;
}
.intro p {
    color: #7f8c8d;
    line-height: 1.6;
}
.tools {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 20px;
}
.tool-card {
    background: white;
    padding: 25px;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    transition: transform 0.2s, box-shadow 0.2s;
}
.tool-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}
.tool-card h3 {
    color: #2c3e50;
    margin-bottom: 10px;
}
.tool-card p {
    color: #7f8c8d;
    font-size: 0.9em;
    margin-bottom: 15px;
    line-height: 1.5;
}
.tool-card a {
    display: inline-block;
    background: #3498db;
    color: white;
    padding: 8px 16px;
    border-radius: 4px;
    text-decoration: none;
    font-size: 0.9em;
}
.tool-card a:hover {
    background: #2980b9;
}
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 15px;
    margin-top: 30px;
}
.stat-box {
    background: white;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    text-align: center;
}
.stat-box .number {
    font-size: 2em;
    font-weight: 700;
    color: #3498db;
}
.stat-box .label {
    font-size: 0.85em;
    color: #7f8c8d;
    margin-top: 5px;
}
"""

HOME_PAGE_CONTENT = """
<div class="container">
    <div class="intro">
        <h2>Welcome to Shelf Viewer</h2>
        <p>A unified debugging interface for the book processing pipeline. Select a tool below to explore your scanned books.</p>
    </div>

    <div class="tools">
        <div class="tool-card">
            <h3>📖 ToC Viewer</h3>
            <p>View parsed table of contents side-by-side with page images. Debug ToC extraction quality and confidence.</p>
            <a href="/toc">Open ToC Viewer →</a>
        </div>

        <div class="tool-card">
            <h3>✏️ Correction Viewer</h3>
            <p>Compare OCR output with corrections. See page images, raw OCR blocks, and corrected text side-by-side.</p>
            <a href="/corrections">Open Corrections →</a>
        </div>

        <div class="tool-card">
            <h3>🏷️ Label Viewer</h3>
            <p>View page labels with visual overlays. See regions, block types, and page numbers highlighted on images.</p>
            <a href="/labels">Open Labels →</a>
        </div>

        <div class="tool-card">
            <h3>📊 Stats Viewer</h3>
            <p>View book-level statistics from labels stage. Analyze page regions, block types, and confidence scores.</p>
            <a href="/stats">Open Stats →</a>
        </div>
    </div>

    <div class="stats-grid">
        <div class="stat-box">
            <div class="number">{{ stats.total_books }}</div>
            <div class="label">Total Books</div>
        </div>
        <div class="stat-box">
            <div class="number">{{ stats.books_with_toc }}</div>
            <div class="label">With ToC</div>
        </div>
        <div class="stat-box">
            <div class="number">{{ stats.books_with_corrections }}</div>
            <div class="label">With Corrections</div>
        </div>
        <div class="stat-box">
            <div class="number">{{ stats.books_with_labels }}</div>
            <div class="label">With Labels</div>
        </div>
    </div>
</div>
"""


@app.route("/")
def home():
    """Home page with tool picker."""
    books = find_all_books()
    stats = {
        "total_books": len(books),
        "books_with_toc": sum(1 for b in books if b["has_toc"]),
        "books_with_corrections": sum(1 for b in books if b["has_corrections"]),
        "books_with_labels": sum(1 for b in books if b["has_labels"]),
    }

    content = render_template_string(HOME_PAGE_CONTENT, stats=stats)
    return render_page("Shelf Viewer - Home", "home", HOME_PAGE_STYLES, content)


# ============================================================================
# ToC Viewer
# ============================================================================

TOC_LIST_TEMPLATE = """
{% extends "base.html" %}
{% block title %}ToC Viewer - Books{% endblock %}

{% block styles %}
.container {
    max-width: 1200px;
    margin: 40px auto;
    padding: 0 20px;
}
h2 {
    color: #2c3e50;
    margin-bottom: 20px;
}
.book-list {
    list-style: none;
}
.book-item {
    background: white;
    margin: 15px 0;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    transition: transform 0.2s, box-shadow 0.2s;
}
.book-item:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.15);
}
.book-item a {
    text-decoration: none;
    color: #3498db;
    font-size: 1.2em;
    font-weight: 600;
}
.book-item a:hover {
    color: #2980b9;
}
.book-meta {
    margin-top: 8px;
    color: #7f8c8d;
    font-size: 0.9em;
}
.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: #7f8c8d;
}
{% endblock %}

{% block content %}
<div class="container">
    <h2>📖 ToC Viewer - Books</h2>
    {% if books %}
    <ul class="book-list">
        {% for book in books %}
        <li class="book-item">
            <a href="/toc/{{ book.scan_id }}">{{ book.scan_id }}</a>
            <div class="book-meta">
                {{ book.entry_count }} ToC entries |
                Pages {{ book.page_range.start_page }}-{{ book.page_range.end_page }}
            </div>
        </li>
        {% endfor %}
    </ul>
    {% else %}
    <div class="empty-state">
        <h3>No books with ToC data found</h3>
        <p>Run the build-structure stage on some books first.</p>
    </div>
    {% endif %}
</div>
{% endblock %}
"""

TOC_VIEWER_TEMPLATE = """
{% extends "base.html" %}
{% block title %}ToC Viewer - {{ scan_id }}{% endblock %}

{% block styles %}
.header {
    background: white;
    padding: 20px 30px;
    border-bottom: 2px solid #ddd;
}
.header h2 {
    color: #2c3e50;
    font-size: 1.3em;
    margin-bottom: 10px;
}
.metadata {
    padding: 10px;
    background: #ecf0f1;
    border-radius: 4px;
    font-size: 0.9em;
}
.metadata span {
    margin-right: 20px;
    color: #7f8c8d;
}
.container {
    display: flex;
    height: calc(100vh - 200px);
}
.images-panel {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    background: #ecf0f1;
}
.page-image {
    margin-bottom: 30px;
    background: white;
    padding: 15px;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
.page-image h3 {
    margin-bottom: 10px;
    color: #2c3e50;
}
.page-image img {
    width: 100%;
    border: 1px solid #bdc3c7;
    border-radius: 4px;
}
.toc-panel {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    background: white;
    border-left: 2px solid #ddd;
}
.toc-entry {
    margin-bottom: 15px;
    padding: 15px;
    background: #ecf0f1;
    border-left: 4px solid #3498db;
    border-radius: 4px;
}
.toc-entry.level-2 {
    margin-left: 20px;
    border-left-color: #95a5a6;
}
.toc-entry.level-3 {
    margin-left: 40px;
    border-left-color: #bdc3c7;
}
.toc-title {
    font-weight: 600;
    color: #2c3e50;
    margin-bottom: 5px;
}
.toc-details {
    font-size: 0.85em;
    color: #7f8c8d;
}
.notes {
    margin-top: 20px;
    padding: 15px;
    background: #fff3cd;
    border-left: 4px solid #ffc107;
    border-radius: 4px;
}
.notes h3 {
    margin-bottom: 10px;
    color: #856404;
}
.notes ul {
    margin-left: 20px;
    color: #856404;
}
{% endblock %}

{% block content %}
<div class="header">
    <h2>{{ scan_id }}</h2>
    <div class="metadata">
        <span><strong>ToC Pages:</strong> {{ toc_data.toc_page_range.start_page }}-{{ toc_data.toc_page_range.end_page }}</span>
        <span><strong>Entries:</strong> {{ toc_data.entries|length }}</span>
        <span><strong>Chapters:</strong> {{ toc_data.total_chapters }}</span>
        <span><strong>Sections:</strong> {{ toc_data.total_sections }}</span>
        <span><strong>Confidence:</strong> {{ "%.2f"|format(toc_data.parsing_confidence) }}</span>
    </div>
</div>

<div class="container">
    <div class="images-panel">
        <h3 style="margin-bottom: 20px; color: #2c3e50;">ToC Page Images</h3>
        {% for page_num in page_numbers %}
        <div class="page-image">
            <h3>Page {{ page_num }}</h3>
            <img src="/image/{{ scan_id }}/{{ page_num }}" alt="Page {{ page_num }}">
        </div>
        {% endfor %}
    </div>

    <div class="toc-panel">
        <h3 style="margin-bottom: 20px; color: #2c3e50;">Parsed ToC Entries</h3>
        {% for entry in toc_data.entries %}
        <div class="toc-entry level-{{ entry.level }}">
            <div class="toc-title">{{ entry.title }}</div>
            <div class="toc-details">
                {% if entry.chapter_number %}Chapter {{ entry.chapter_number }} | {% endif %}
                {% if entry.printed_page_number %}Printed Page: {{ entry.printed_page_number }}{% else %}Page: N/A{% endif %} |
                Level {{ entry.level }}
            </div>
        </div>
        {% endfor %}

        {% if toc_data.notes %}
        <div class="notes">
            <h3>⚠️ Parsing Notes</h3>
            <ul>
                {% for note in toc_data.notes %}
                <li>{{ note }}</li>
                {% endfor %}
            </ul>
        </div>
        {% endif %}
    </div>
</div>
{% endblock %}
"""


@app.route("/toc")
def toc_list():
    """List books with ToC data."""
    books = []
    for book_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith('.'):
            continue
        toc_path = book_dir / "build_structure" / "toc.json"
        if toc_path.exists():
            with open(toc_path) as f:
                toc_data = json.load(f)
            # Skip if no ToC found
            if "note" in toc_data and "No ToC found" in toc_data["note"]:
                continue
            books.append({
                "scan_id": book_dir.name,
                "entry_count": len(toc_data.get("entries", [])),
                "page_range": toc_data.get("toc_page_range", {}),
            })

    base = render_template_string(BASE_TEMPLATE, active_page='toc', content="")
    content = render_template_string(TOC_LIST_TEMPLATE, books=books)
    return base.replace("{% block content %}{% endblock %}", content)


@app.route("/toc/<scan_id>")
def toc_view(scan_id: str):
    """View ToC for a specific book."""
    toc_path = LIBRARY_ROOT / scan_id / "build_structure" / "toc.json"
    if not toc_path.exists():
        abort(404, f"No ToC data found for {scan_id}")

    with open(toc_path) as f:
        toc_data = json.load(f)

    page_range = toc_data.get("toc_page_range", {})
    start_page = page_range.get("start_page", 1)
    end_page = page_range.get("end_page", 1)
    page_numbers = list(range(start_page, end_page + 1))

    base = render_template_string(BASE_TEMPLATE, active_page='toc', content="")
    content = render_template_string(
        TOC_VIEWER_TEMPLATE,
        scan_id=scan_id,
        toc_data=toc_data,
        page_numbers=page_numbers,
    )
    return base.replace("{% block content %}{% endblock %}", content)


# ============================================================================
# Correction Viewer
# ============================================================================

CORRECTION_LIST_TEMPLATE = """
{% extends "base.html" %}
{% block title %}Correction Viewer - Books{% endblock %}

{% block styles %}
.container {
    max-width: 1200px;
    margin: 40px auto;
    padding: 0 20px;
}
h2 {
    color: #2c3e50;
    margin-bottom: 20px;
}
.book-list {
    list-style: none;
}
.book-item {
    background: white;
    margin: 15px 0;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    transition: transform 0.2s, box-shadow 0.2s;
}
.book-item:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.15);
}
.book-item a {
    text-decoration: none;
    color: #3498db;
    font-size: 1.2em;
    font-weight: 600;
}
.book-item a:hover {
    color: #2980b9;
}
.book-meta {
    margin-top: 8px;
    color: #7f8c8d;
    font-size: 0.9em;
}
.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: #7f8c8d;
}
{% endblock %}

{% block content %}
<div class="container">
    <h2>✏️ Correction Viewer - Books</h2>
    {% if books %}
    <ul class="book-list">
        {% for book in books %}
        <li class="book-item">
            <a href="/corrections/{{ book.scan_id }}">{{ book.scan_id }}</a>
            <div class="book-meta">{{ book.page_count }} pages</div>
        </li>
        {% endfor %}
    </ul>
    {% else %}
    <div class="empty-state">
        <h3>No books with corrections found</h3>
        <p>Run the corrections stage on some books first.</p>
    </div>
    {% endif %}
</div>
{% endblock %}
"""

CORRECTION_VIEWER_TEMPLATE = """
{% extends "base.html" %}
{% block title %}Correction Viewer - {{ scan_id }}{% endblock %}

{% block styles %}
.header {
    background: white;
    padding: 20px 30px;
    border-bottom: 2px solid #ddd;
}
.header h2 {
    color: #2c3e50;
    margin-bottom: 10px;
}
.page-selector {
    margin-top: 15px;
}
.page-selector select {
    padding: 8px 12px;
    border: 1px solid #bdc3c7;
    border-radius: 4px;
    font-size: 0.9em;
}
.page-selector button {
    padding: 8px 16px;
    margin-left: 10px;
    background: #3498db;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.9em;
}
.page-selector button:hover {
    background: #2980b9;
}
.container {
    display: flex;
    height: calc(100vh - 200px);
}
.image-panel {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    background: #ecf0f1;
}
.image-panel img {
    width: 100%;
    border: 1px solid #bdc3c7;
    border-radius: 4px;
    background: white;
}
.text-panels {
    flex: 2;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    background: white;
    border-left: 2px solid #ddd;
}
.text-section {
    flex: 1;
    padding: 20px;
    overflow-y: auto;
}
.text-section:first-child {
    border-bottom: 2px solid #ddd;
}
.text-section h3 {
    color: #2c3e50;
    margin-bottom: 15px;
    padding-bottom: 10px;
    border-bottom: 2px solid #ecf0f1;
}
.block {
    margin-bottom: 20px;
    padding: 15px;
    background: #ecf0f1;
    border-radius: 4px;
    font-family: 'Courier New', monospace;
    font-size: 0.85em;
    line-height: 1.6;
}
.block-header {
    color: #7f8c8d;
    font-size: 0.8em;
    margin-bottom: 8px;
}
.block-text {
    color: #2c3e50;
}
.no-data {
    color: #95a5a6;
    font-style: italic;
    text-align: center;
    padding: 40px;
}
{% endblock %}

{% block content %}
<div class="header">
    <h2>{{ scan_id }}</h2>
    <div class="page-selector">
        <label for="page-select">Page:</label>
        <select id="page-select" onchange="window.location.href='/corrections/{{ scan_id }}/' + this.value">
            {% for p in all_pages %}
            <option value="{{ p }}" {% if p == current_page %}selected{% endif %}>{{ p }}</option>
            {% endfor %}
        </select>
        {% if current_page > 1 %}
        <button onclick="window.location.href='/corrections/{{ scan_id }}/{{ current_page - 1 }}'">← Previous</button>
        {% endif %}
        {% if current_page < all_pages|length %}
        <button onclick="window.location.href='/corrections/{{ scan_id }}/{{ current_page + 1 }}'">Next →</button>
        {% endif %}
    </div>
</div>

<div class="container">
    <div class="image-panel">
        <h3 style="margin-bottom: 15px; color: #2c3e50;">Page Image</h3>
        <img src="/image/{{ scan_id }}/{{ current_page }}" alt="Page {{ current_page }}">
    </div>

    <div class="text-panels">
        <div class="text-section">
            <h3>OCR Output</h3>
            {% if ocr_data %}
                {% for block in ocr_data.blocks %}
                <div class="block">
                    <div class="block-header">Block {{ loop.index }} | Confidence: {{ "%.2f"|format(block.confidence) }}</div>
                    <div class="block-text">
                        {% for para in block.paragraphs %}
                        <p>{{ para.text }}</p>
                        {% endfor %}
                    </div>
                </div>
                {% endfor %}
            {% else %}
            <div class="no-data">No OCR data available</div>
            {% endif %}
        </div>

        <div class="text-section">
            <h3>Corrections</h3>
            {% if correction_data %}
                {% for block in correction_data.blocks %}
                <div class="block">
                    <div class="block-header">Block {{ loop.index }}</div>
                    <div class="block-text">
                        {% for para in block.paragraphs %}
                        <p>{{ para.text }}</p>
                        {% endfor %}
                    </div>
                </div>
                {% endfor %}
            {% else %}
            <div class="no-data">No correction data available</div>
            {% endif %}
        </div>
    </div>
</div>
{% endblock %}
"""


@app.route("/corrections")
def correction_list():
    """List books with correction data."""
    books = []
    for book_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith('.'):
            continue
        corrections_dir = book_dir / "corrections"
        if corrections_dir.exists():
            page_count = len(list(corrections_dir.glob("page_*.json")))
            if page_count > 0:
                books.append({
                    "scan_id": book_dir.name,
                    "page_count": page_count,
                })

    base = render_template_string(BASE_TEMPLATE, active_page='corrections', content="")
    content = render_template_string(CORRECTION_LIST_TEMPLATE, books=books)
    return base.replace("{% block content %}{% endblock %}", content)


@app.route("/corrections/<scan_id>")
@app.route("/corrections/<scan_id>/<int:page_num>")
def correction_view(scan_id: str, page_num: int = None):
    """View corrections for a specific book page."""
    all_pages = get_book_pages(scan_id)
    if not all_pages:
        abort(404, f"No pages found for {scan_id}")

    if page_num is None:
        page_num = all_pages[0]

    if page_num not in all_pages:
        abort(404, f"Page {page_num} not found")

    ocr_data = get_stage_data(scan_id, "ocr", page_num)
    correction_data = get_stage_data(scan_id, "corrections", page_num)

    base = render_template_string(BASE_TEMPLATE, active_page='corrections', content="")
    content = render_template_string(
        CORRECTION_VIEWER_TEMPLATE,
        scan_id=scan_id,
        current_page=page_num,
        all_pages=all_pages,
        ocr_data=ocr_data,
        correction_data=correction_data,
    )
    return base.replace("{% block content %}{% endblock %}", content)


# ============================================================================
# Label Viewer
# ============================================================================

LABEL_LIST_TEMPLATE = """
{% extends "base.html" %}
{% block title %}Label Viewer - Books{% endblock %}

{% block styles %}
.container {
    max-width: 1200px;
    margin: 40px auto;
    padding: 0 20px;
}
h2 {
    color: #2c3e50;
    margin-bottom: 20px;
}
.book-list {
    list-style: none;
}
.book-item {
    background: white;
    margin: 15px 0;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    transition: transform 0.2s, box-shadow 0.2s;
}
.book-item:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.15);
}
.book-item a {
    text-decoration: none;
    color: #3498db;
    font-size: 1.2em;
    font-weight: 600;
}
.book-item a:hover {
    color: #2980b9;
}
.book-meta {
    margin-top: 8px;
    color: #7f8c8d;
    font-size: 0.9em;
}
.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: #7f8c8d;
}
{% endblock %}

{% block content %}
<div class="container">
    <h2>🏷️ Label Viewer - Books</h2>
    {% if books %}
    <ul class="book-list">
        {% for book in books %}
        <li class="book-item">
            <a href="/labels/{{ book.scan_id }}">{{ book.scan_id }}</a>
            <div class="book-meta">{{ book.page_count }} pages</div>
        </li>
        {% endfor %}
    </ul>
    {% else %}
    <div class="empty-state">
        <h3>No books with labels found</h3>
        <p>Run the labels stage on some books first.</p>
    </div>
    {% endif %}
</div>
{% endblock %}
"""

LABEL_VIEWER_TEMPLATE = """
{% extends "base.html" %}
{% block title %}Label Viewer - {{ scan_id }}{% endblock %}

{% block styles %}
.header {
    background: white;
    padding: 20px 30px;
    border-bottom: 2px solid #ddd;
}
.header h2 {
    color: #2c3e50;
    margin-bottom: 10px;
}
.page-selector {
    margin-top: 15px;
}
.page-selector select {
    padding: 8px 12px;
    border: 1px solid #bdc3c7;
    border-radius: 4px;
    font-size: 0.9em;
}
.page-selector button {
    padding: 8px 16px;
    margin-left: 10px;
    background: #3498db;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.9em;
}
.page-selector button:hover {
    background: #2980b9;
}
.container {
    display: flex;
    height: calc(100vh - 200px);
}
.image-panel {
    flex: 2;
    overflow-y: auto;
    padding: 20px;
    background: #ecf0f1;
    position: relative;
}
.image-wrapper {
    position: relative;
    display: inline-block;
}
.image-wrapper img {
    width: 100%;
    border: 1px solid #bdc3c7;
    border-radius: 4px;
    background: white;
}
.overlay-canvas {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
}
.metadata-panel {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    background: white;
    border-left: 2px solid #ddd;
}
.metadata-panel h3 {
    color: #2c3e50;
    margin-bottom: 15px;
    padding-bottom: 10px;
    border-bottom: 2px solid #ecf0f1;
}
.metadata-item {
    margin-bottom: 15px;
    padding: 12px;
    background: #ecf0f1;
    border-radius: 4px;
    font-size: 0.85em;
}
.metadata-item .label {
    font-weight: 600;
    color: #2c3e50;
    margin-bottom: 5px;
}
.metadata-item .value {
    color: #7f8c8d;
}
.block-list {
    margin-top: 20px;
}
.block-item {
    margin-bottom: 10px;
    padding: 10px;
    background: #ecf0f1;
    border-left: 4px solid #3498db;
    border-radius: 4px;
    font-size: 0.85em;
}
.block-item .block-type {
    font-weight: 600;
    color: #2c3e50;
}
.block-item .block-details {
    color: #7f8c8d;
    margin-top: 5px;
}
.legend {
    margin-top: 20px;
    padding: 15px;
    background: #ecf0f1;
    border-radius: 4px;
}
.legend-item {
    display: flex;
    align-items: center;
    margin-bottom: 8px;
}
.legend-color {
    width: 20px;
    height: 20px;
    margin-right: 10px;
    border: 1px solid #95a5a6;
    border-radius: 3px;
}
.legend-label {
    font-size: 0.85em;
    color: #2c3e50;
}
{% endblock %}

{% block content %}
<div class="header">
    <h2>{{ scan_id }}</h2>
    <div class="page-selector">
        <label for="page-select">Page:</label>
        <select id="page-select" onchange="window.location.href='/labels/{{ scan_id }}/' + this.value">
            {% for p in all_pages %}
            <option value="{{ p }}" {% if p == current_page %}selected{% endif %}>{{ p }}</option>
            {% endfor %}
        </select>
        {% if current_page > 1 %}
        <button onclick="window.location.href='/labels/{{ scan_id }}/{{ current_page - 1 }}'">← Previous</button>
        {% endif %}
        {% if current_page < all_pages|length %}
        <button onclick="window.location.href='/labels/{{ scan_id }}/{{ current_page + 1 }}'">Next →</button>
        {% endif %}
    </div>
</div>

<div class="container">
    <div class="image-panel">
        <h3 style="margin-bottom: 15px; color: #2c3e50;">Page Image with Label Overlays</h3>
        <div class="image-wrapper">
            <img id="page-image" src="/image/{{ scan_id }}/{{ current_page }}" alt="Page {{ current_page }}" onload="drawOverlays()">
            <canvas id="overlay-canvas" class="overlay-canvas"></canvas>
        </div>
    </div>

    <div class="metadata-panel">
        <h3>Page Labels</h3>

        {% if label_data %}
        <div class="metadata-item">
            <div class="label">Page Number</div>
            <div class="value">{{ label_data.page_num }}</div>
        </div>

        <div class="metadata-item">
            <div class="label">Printed Page Number</div>
            <div class="value">{{ label_data.printed_page_number or "N/A" }}</div>
        </div>

        <div class="metadata-item">
            <div class="label">Page Region</div>
            <div class="value">{{ label_data.page_region }}</div>
        </div>

        <div class="metadata-item">
            <div class="label">Has Chapter Heading</div>
            <div class="value">{{ "Yes" if label_data.has_chapter_heading else "No" }}</div>
        </div>

        <div class="block-list">
            <h4 style="color: #2c3e50; margin-bottom: 10px;">Blocks ({{ label_data.blocks|length }})</h4>
            {% for block in label_data.blocks %}
            <div class="block-item">
                <div class="block-type">{{ block.block_type }}</div>
                <div class="block-details">
                    Confidence: {{ "%.2f"|format(block.confidence) }}
                </div>
            </div>
            {% endfor %}
        </div>

        <div class="legend">
            <h4 style="color: #2c3e50; margin-bottom: 10px;">Legend</h4>
            <div class="legend-item">
                <div class="legend-color" style="background: rgba(52, 152, 219, 0.3);"></div>
                <div class="legend-label">Blocks</div>
            </div>
        </div>
        {% else %}
        <div style="color: #95a5a6; font-style: italic; text-align: center; padding: 40px;">
            No label data available
        </div>
        {% endif %}
    </div>
</div>

<script>
// Draw block overlays on the image
function drawOverlays() {
    const img = document.getElementById('page-image');
    const canvas = document.getElementById('overlay-canvas');
    const ctx = canvas.getContext('2d');

    // Match canvas size to image
    canvas.width = img.width;
    canvas.height = img.height;

    // Get label data (injected from server)
    const labelData = {{ label_data|tojson|safe }};
    if (!labelData || !labelData.blocks) return;

    // Get image dimensions
    const imgWidth = {{ image_width }};
    const imgHeight = {{ image_height }};

    // Calculate scale
    const scaleX = canvas.width / imgWidth;
    const scaleY = canvas.height / imgHeight;

    // Draw each block
    labelData.blocks.forEach((block, idx) => {
        const bbox = block.bbox;

        // Scale coordinates
        const x = bbox.x0 * scaleX;
        const y = bbox.y0 * scaleY;
        const width = (bbox.x1 - bbox.x0) * scaleX;
        const height = (bbox.y1 - bbox.y0) * scaleY;

        // Draw rectangle
        ctx.strokeStyle = 'rgba(52, 152, 219, 0.8)';
        ctx.lineWidth = 2;
        ctx.strokeRect(x, y, width, height);

        // Draw semi-transparent fill
        ctx.fillStyle = 'rgba(52, 152, 219, 0.1)';
        ctx.fillRect(x, y, width, height);

        // Draw block number
        ctx.fillStyle = 'rgba(52, 152, 219, 0.9)';
        ctx.font = '14px sans-serif';
        ctx.fillText(String(idx + 1), x + 5, y + 18);
    });
}

// Redraw on window resize
window.addEventListener('resize', drawOverlays);
</script>
{% endblock %}
"""


@app.route("/labels")
def label_list():
    """List books with label data."""
    books = []
    for book_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith('.'):
            continue
        labels_dir = book_dir / "labels"
        if labels_dir.exists():
            page_count = len(list(labels_dir.glob("page_*.json")))
            if page_count > 0:
                books.append({
                    "scan_id": book_dir.name,
                    "page_count": page_count,
                })

    base = render_template_string(BASE_TEMPLATE, active_page='labels', content="")
    content = render_template_string(LABEL_LIST_TEMPLATE, books=books)
    return base.replace("{% block content %}{% endblock %}", content)


@app.route("/labels/<scan_id>")
@app.route("/labels/<scan_id>/<int:page_num>")
def label_view(scan_id: str, page_num: int = None):
    """View labels for a specific book page."""
    all_pages = get_book_pages(scan_id)
    if not all_pages:
        abort(404, f"No pages found for {scan_id}")

    if page_num is None:
        page_num = all_pages[0]

    if page_num not in all_pages:
        abort(404, f"Page {page_num} not found")

    label_data = get_stage_data(scan_id, "labels", page_num)

    # Get image dimensions (for overlay scaling)
    from PIL import Image
    img_path = get_page_image_path(scan_id, page_num)
    with Image.open(img_path) as img:
        image_width, image_height = img.size

    base = render_template_string(BASE_TEMPLATE, active_page='labels', content="")
    content = render_template_string(
        LABEL_VIEWER_TEMPLATE,
        scan_id=scan_id,
        current_page=page_num,
        all_pages=all_pages,
        label_data=label_data,
        image_width=image_width,
        image_height=image_height,
    )
    return base.replace("{% block content %}{% endblock %}", content)


# ============================================================================
# Stats Viewer
# ============================================================================

STATS_LIST_TEMPLATE = """
{% extends "base.html" %}
{% block title %}Stats Viewer - Books{% endblock %}

{% block styles %}
.container {
    max-width: 1200px;
    margin: 40px auto;
    padding: 0 20px;
}
h2 {
    color: #2c3e50;
    margin-bottom: 20px;
}
.book-list {
    list-style: none;
}
.book-item {
    background: white;
    margin: 15px 0;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    transition: transform 0.2s, box-shadow 0.2s;
}
.book-item:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.15);
}
.book-item a {
    text-decoration: none;
    color: #3498db;
    font-size: 1.2em;
    font-weight: 600;
}
.book-item a:hover {
    color: #2980b9;
}
.book-meta {
    margin-top: 8px;
    color: #7f8c8d;
    font-size: 0.9em;
}
.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: #7f8c8d;
}
{% endblock %}

{% block content %}
<div class="container">
    <h2>📊 Stats Viewer - Books</h2>
    {% if books %}
    <ul class="book-list">
        {% for book in books %}
        <li class="book-item">
            <a href="/stats/{{ book.scan_id }}">{{ book.scan_id }}</a>
            <div class="book-meta">{{ book.page_count }} pages analyzed</div>
        </li>
        {% endfor %}
    </ul>
    {% else %}
    <div class="empty-state">
        <h3>No books with stats found</h3>
        <p>Run the labels stage on some books first.</p>
    </div>
    {% endif %}
</div>
{% endblock %}
"""

STATS_VIEWER_TEMPLATE = """
{% extends "base.html" %}
{% block title %}Stats Viewer - {{ scan_id }}{% endblock %}

{% block styles %}
.container {
    max-width: 1400px;
    margin: 40px auto;
    padding: 0 20px;
}
.header {
    background: white;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    margin-bottom: 30px;
}
.header h2 {
    color: #2c3e50;
}
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 20px;
    margin-bottom: 30px;
}
.stat-card {
    background: white;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
.stat-card h3 {
    color: #2c3e50;
    font-size: 0.9em;
    margin-bottom: 15px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.stat-number {
    font-size: 2.5em;
    font-weight: 700;
    color: #3498db;
}
.breakdown-section {
    background: white;
    padding: 25px;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    margin-bottom: 30px;
}
.breakdown-section h3 {
    color: #2c3e50;
    margin-bottom: 20px;
    padding-bottom: 10px;
    border-bottom: 2px solid #ecf0f1;
}
.breakdown-list {
    list-style: none;
}
.breakdown-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px;
    margin-bottom: 8px;
    background: #ecf0f1;
    border-radius: 4px;
}
.breakdown-label {
    font-weight: 500;
    color: #2c3e50;
}
.breakdown-value {
    font-weight: 600;
    color: #3498db;
}
.breakdown-bar {
    margin-left: 10px;
    height: 8px;
    background: #3498db;
    border-radius: 4px;
    min-width: 20px;
}
table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
table th {
    background: #2c3e50;
    color: white;
    padding: 12px;
    text-align: left;
    font-size: 0.85em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
table td {
    padding: 12px;
    border-bottom: 1px solid #ecf0f1;
    font-size: 0.9em;
    color: #2c3e50;
}
table tr:last-child td {
    border-bottom: none;
}
table tr:hover {
    background: #f8f9fa;
}
{% endblock %}

{% block content %}
<div class="container">
    <div class="header">
        <h2>{{ scan_id }} - Label Statistics</h2>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <h3>Total Pages</h3>
            <div class="stat-number">{{ stats.total_pages }}</div>
        </div>

        <div class="stat-card">
            <h3>Total Blocks</h3>
            <div class="stat-number">{{ stats.total_blocks }}</div>
        </div>

        <div class="stat-card">
            <h3>Avg Confidence</h3>
            <div class="stat-number">{{ "%.2f"|format(stats.avg_confidence) }}</div>
        </div>

        <div class="stat-card">
            <h3>Chapter Headings</h3>
            <div class="stat-number">{{ stats.chapter_headings }}</div>
        </div>
    </div>

    <div class="breakdown-section">
        <h3>Page Regions</h3>
        <ul class="breakdown-list">
            {% for region, count in stats.region_breakdown.items() %}
            <li class="breakdown-item">
                <span class="breakdown-label">{{ region }}</span>
                <div style="display: flex; align-items: center;">
                    <span class="breakdown-value">{{ count }}</span>
                    <div class="breakdown-bar" style="width: {{ (count / stats.total_pages * 200)|int }}px;"></div>
                </div>
            </li>
            {% endfor %}
        </ul>
    </div>

    <div class="breakdown-section">
        <h3>Block Types</h3>
        <ul class="breakdown-list">
            {% for block_type, count in stats.block_type_breakdown.items() %}
            <li class="breakdown-item">
                <span class="breakdown-label">{{ block_type }}</span>
                <div style="display: flex; align-items: center;">
                    <span class="breakdown-value">{{ count }}</span>
                    <div class="breakdown-bar" style="width: {{ (count / stats.total_blocks * 200)|int }}px;"></div>
                </div>
            </li>
            {% endfor %}
        </ul>
    </div>

    <div class="breakdown-section">
        <h3>Sample Pages (First 50)</h3>
        <table>
            <thead>
                <tr>
                    <th>Page</th>
                    <th>Printed Page</th>
                    <th>Region</th>
                    <th>Blocks</th>
                    <th>Chapter Heading</th>
                    <th>Avg Confidence</th>
                </tr>
            </thead>
            <tbody>
                {% for row in stats.sample_pages %}
                <tr>
                    <td>{{ row.page_num }}</td>
                    <td>{{ row.printed_page_number or "N/A" }}</td>
                    <td>{{ row.page_region }}</td>
                    <td>{{ row.block_count }}</td>
                    <td>{{ "Yes" if row.has_chapter_heading else "No" }}</td>
                    <td>{{ "%.2f"|format(row.avg_confidence) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
{% endblock %}
"""


@app.route("/stats")
def stats_list():
    """List books with stats."""
    books = []
    for book_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith('.'):
            continue
        report_path = book_dir / "labels" / "report.csv"
        if report_path.exists():
            with open(report_path) as f:
                page_count = sum(1 for _ in csv.DictReader(f))
            books.append({
                "scan_id": book_dir.name,
                "page_count": page_count,
            })

    base = render_template_string(BASE_TEMPLATE, active_page='stats', content="")
    content = render_template_string(STATS_LIST_TEMPLATE, books=books)
    return base.replace("{% block content %}{% endblock %}", content)


@app.route("/stats/<scan_id>")
def stats_view(scan_id: str):
    """View stats for a specific book."""
    report_path = LIBRARY_ROOT / scan_id / "labels" / "report.csv"
    if not report_path.exists():
        abort(404, f"No stats found for {scan_id}")

    # Parse report.csv
    with open(report_path) as f:
        rows = list(csv.DictReader(f))

    # Calculate statistics
    total_pages = len(rows)
    total_blocks = sum(int(row.get('block_count', 0)) for row in rows)
    chapter_headings = sum(1 for row in rows if row.get('has_chapter_heading', '').lower() == 'true')

    # Calculate average confidence
    confidences = [float(row.get('avg_confidence', 0)) for row in rows if row.get('avg_confidence')]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    # Region breakdown
    region_breakdown = {}
    for row in rows:
        region = row.get('page_region', 'unknown')
        region_breakdown[region] = region_breakdown.get(region, 0) + 1

    # Block type breakdown (aggregate across all pages)
    block_type_breakdown = {}
    for row in rows:
        # Parse block_types field (comma-separated)
        block_types = row.get('block_types', '').split(',')
        for bt in block_types:
            bt = bt.strip()
            if bt:
                block_type_breakdown[bt] = block_type_breakdown.get(bt, 0) + 1

    # Sample pages (first 50)
    sample_pages = []
    for row in rows[:50]:
        sample_pages.append({
            "page_num": int(row['page_num']),
            "printed_page_number": row.get('printed_page_number'),
            "page_region": row.get('page_region', 'unknown'),
            "block_count": int(row.get('block_count', 0)),
            "has_chapter_heading": row.get('has_chapter_heading', '').lower() == 'true',
            "avg_confidence": float(row.get('avg_confidence', 0)),
        })

    stats = {
        "total_pages": total_pages,
        "total_blocks": total_blocks,
        "avg_confidence": avg_confidence,
        "chapter_headings": chapter_headings,
        "region_breakdown": region_breakdown,
        "block_type_breakdown": block_type_breakdown,
        "sample_pages": sample_pages,
    }

    base = render_template_string(BASE_TEMPLATE, active_page='stats', content="")
    content = render_template_string(STATS_VIEWER_TEMPLATE, scan_id=scan_id, stats=stats)
    return base.replace("{% block content %}{% endblock %}", content)


# ============================================================================
# Image Server
# ============================================================================

@app.route("/image/<scan_id>/<int:page_num>")
def serve_image(scan_id: str, page_num: int):
    """Serve page image."""
    img_path = get_page_image_path(scan_id, page_num)
    if not img_path:
        abort(404, f"Image not found for page {page_num}")
    return send_file(img_path)


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Shelf Viewer - Unified debugging interface")
    parser.add_argument("--port", type=int, default=5000, help="Port to run on (default: 5000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    args = parser.parse_args()

    print(f"\n🚀 Shelf Viewer starting on http://{args.host}:{args.port}")
    print(f"📁 Library: {LIBRARY_ROOT}\n")
    print(f"Available tools:")
    print(f"  📖 ToC Viewer      - http://{args.host}:{args.port}/toc")
    print(f"  ✏️  Corrections     - http://{args.host}:{args.port}/corrections")
    print(f"  🏷️  Labels          - http://{args.host}:{args.port}/labels")
    print(f"  📊 Stats           - http://{args.host}:{args.port}/stats")
    print(f"\n✨ Open http://{args.host}:{args.port} in your browser\n")

    app.run(host=args.host, port=args.port, debug=True)
