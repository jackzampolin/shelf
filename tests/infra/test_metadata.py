"""Tests for infra/metadata.py"""

import json
from pathlib import Path
from infra.storage.metadata import (
    update_book_metadata,
    get_latest_processing_record,
    get_scan_total_cost,
    get_scan_models,
    format_processing_summary
)


def test_update_and_retrieve_metadata(tmp_path):
    """Test writing and reading processing metadata."""
    book_dir = tmp_path / "test-book"
    book_dir.mkdir()

    # Add OCR metadata
    update_book_metadata(book_dir, "ocr", {
        "pages_processed": 100,
        "cost_usd": 0.0,
        "model": "tesseract"
    })

    # Add correction metadata
    update_book_metadata(book_dir, "correct", {
        "pages_processed": 100,
        "cost_usd": 5.25,
        "model": "gpt-4o-mini"
    })

    # Retrieve latest correction record
    record = get_latest_processing_record(book_dir, "correct")
    assert record is not None
    assert record["stage"] == "correct"
    assert record["cost_usd"] == 5.25
    assert record["model"] == "gpt-4o-mini"


def test_total_cost_calculation(tmp_path):
    """Test that total cost sums across all stages."""
    book_dir = tmp_path / "test-book"
    book_dir.mkdir()

    update_book_metadata(book_dir, "ocr", {"cost_usd": 0.0})
    update_book_metadata(book_dir, "correct", {"cost_usd": 5.25})
    update_book_metadata(book_dir, "fix", {"cost_usd": 1.50})

    total = get_scan_total_cost(book_dir)
    assert total == 6.75


def test_get_models_used(tmp_path):
    """Test extracting models used per stage."""
    book_dir = tmp_path / "test-book"
    book_dir.mkdir()

    update_book_metadata(book_dir, "ocr", {"model": "tesseract"})
    update_book_metadata(book_dir, "correct", {"model": "gpt-4o-mini"})
    update_book_metadata(book_dir, "structure", {"model": "claude-sonnet-4.5"})

    models = get_scan_models(book_dir)
    assert models["ocr"] == "tesseract"
    assert models["correct"] == "gpt-4o-mini"
    assert models["structure"] == "claude-sonnet-4.5"


def test_processing_summary_format(tmp_path):
    """Test that summary generates readable output."""
    book_dir = tmp_path / "test-book"
    book_dir.mkdir()

    update_book_metadata(book_dir, "ocr", {
        "cost_usd": 0.0,
        "model": "tesseract",
        "pages_processed": 100
    })

    summary = format_processing_summary(book_dir)
    assert "Processing Summary:" in summary
    assert "OCR:" in summary
    assert "tesseract" in summary
    assert "Total Cost:" in summary
