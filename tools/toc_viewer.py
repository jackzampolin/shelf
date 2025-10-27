#!/usr/bin/env python3
"""
ToC Viewer - Simple Flask app for debugging ToC extraction.

Displays page images side-by-side with parsed ToC data for review.

Usage:
    python tools/toc_viewer.py [--port 5000]
"""

import json
import os
from pathlib import Path
from typing import Optional

from flask import Flask, render_template_string, send_file, abort

app = Flask(__name__)

# Get library root from env or default
LIBRARY_ROOT = Path(os.getenv("BOOK_STORAGE_ROOT", "~/Documents/book_scans")).expanduser()


def find_books_with_toc():
    """Find all books in library that have ToC data."""
    books = []
    for book_dir in sorted(LIBRARY_ROOT.iterdir()):
        if not book_dir.is_dir():
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
                "toc_path": toc_path,
                "entry_count": len(toc_data.get("entries", [])),
                "page_range": toc_data.get("toc_page_range", {}),
            })
    return books


def get_toc_data(scan_id: str) -> Optional[dict]:
    """Load ToC data for a book."""
    toc_path = LIBRARY_ROOT / scan_id / "build_structure" / "toc.json"
    if not toc_path.exists():
        return None
    with open(toc_path) as f:
        return json.load(f)


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


# HTML Templates (hardcoded for simplicity)
INDEX_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ToC Viewer - Book Library</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            max-width: 1200px;
            margin: 40px auto;
            padding: 0 20px;
            background: #f5f5f5;
        }
        h1 {
            color: #333;
            border-bottom: 3px solid #007bff;
            padding-bottom: 10px;
        }
        .book-list {
            list-style: none;
            padding: 0;
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
            color: #007bff;
            font-size: 1.2em;
            font-weight: 600;
        }
        .book-item a:hover {
            color: #0056b3;
        }
        .book-meta {
            margin-top: 8px;
            color: #666;
            font-size: 0.9em;
        }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #666;
        }
    </style>
</head>
<body>
    <h1>📚 ToC Viewer - Book Library</h1>
    {% if books %}
    <ul class="book-list">
        {% for book in books %}
        <li class="book-item">
            <a href="/book/{{ book.scan_id }}">{{ book.scan_id }}</a>
            <div class="book-meta">
                {{ book.entry_count }} ToC entries |
                Pages {{ book.page_range.start_page }}-{{ book.page_range.end_page }}
            </div>
        </li>
        {% endfor %}
    </ul>
    {% else %}
    <div class="empty-state">
        <h2>No books with ToC data found</h2>
        <p>Run the build-structure stage on some books first.</p>
    </div>
    {% endif %}
</body>
</html>
"""

VIEWER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ToC Viewer - {{ scan_id }}</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f5f5;
        }
        .header {
            background: white;
            padding: 20px;
            border-bottom: 2px solid #ddd;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .header h1 {
            color: #333;
            font-size: 1.5em;
        }
        .header a {
            color: #007bff;
            text-decoration: none;
            font-size: 0.9em;
        }
        .header a:hover {
            text-decoration: underline;
        }
        .metadata {
            margin-top: 10px;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 4px;
            font-size: 0.9em;
        }
        .metadata span {
            margin-right: 20px;
            color: #666;
        }
        .container {
            display: flex;
            height: calc(100vh - 140px);
        }
        .images-panel {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            background: #e9ecef;
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
            color: #495057;
            font-size: 1.1em;
        }
        .page-image img {
            width: 100%;
            border: 1px solid #dee2e6;
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
            background: #f8f9fa;
            border-left: 4px solid #007bff;
            border-radius: 4px;
        }
        .toc-entry.level-2 {
            margin-left: 20px;
            border-left-color: #6c757d;
        }
        .toc-entry.level-3 {
            margin-left: 40px;
            border-left-color: #adb5bd;
        }
        .toc-title {
            font-weight: 600;
            color: #212529;
            margin-bottom: 5px;
        }
        .toc-details {
            font-size: 0.85em;
            color: #6c757d;
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
    </style>
</head>
<body>
    <div class="header">
        <a href="/">← Back to Library</a>
        <h1>{{ scan_id }}</h1>
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
            <h2 style="margin-bottom: 20px; color: #495057;">ToC Page Images</h2>
            {% for page_num in page_numbers %}
            <div class="page-image">
                <h3>Page {{ page_num }}</h3>
                <img src="/image/{{ scan_id }}/{{ page_num }}" alt="Page {{ page_num }}">
            </div>
            {% endfor %}
        </div>

        <div class="toc-panel">
            <h2 style="margin-bottom: 20px; color: #495057;">Parsed ToC Entries</h2>
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
</body>
</html>
"""


@app.route("/")
def index():
    """List all books with ToC data."""
    books = find_books_with_toc()
    return render_template_string(INDEX_TEMPLATE, books=books)


@app.route("/book/<scan_id>")
def view_book(scan_id: str):
    """View ToC for a specific book."""
    toc_data = get_toc_data(scan_id)
    if not toc_data:
        abort(404, f"No ToC data found for {scan_id}")

    # Get page range
    page_range = toc_data.get("toc_page_range", {})
    start_page = page_range.get("start_page", 1)
    end_page = page_range.get("end_page", 1)
    page_numbers = list(range(start_page, end_page + 1))

    return render_template_string(
        VIEWER_TEMPLATE,
        scan_id=scan_id,
        toc_data=toc_data,
        page_numbers=page_numbers,
    )


@app.route("/image/<scan_id>/<int:page_num>")
def serve_image(scan_id: str, page_num: int):
    """Serve page image."""
    img_path = get_page_image_path(scan_id, page_num)
    if not img_path:
        abort(404, f"Image not found for page {page_num}")
    return send_file(img_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ToC Viewer - Debug ToC extraction")
    parser.add_argument("--port", type=int, default=5000, help="Port to run on (default: 5000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    args = parser.parse_args()

    print(f"\n🚀 ToC Viewer starting on http://{args.host}:{args.port}")
    print(f"📁 Library: {LIBRARY_ROOT}")
    print(f"\n✨ Open http://{args.host}:{args.port} in your browser\n")

    app.run(host=args.host, port=args.port, debug=True)
