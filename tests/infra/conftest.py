"""
Shared fixtures for infra/pipeline tests.

All tests use real filesystem operations with temporary directories.
No mocking - we test actual behavior.
"""

import json
import pytest
from pathlib import Path
from PIL import Image


@pytest.fixture
def tmp_library(tmp_path):
    """Create a temporary library directory structure."""
    library_root = tmp_path / "library"
    library_root.mkdir()
    return library_root


@pytest.fixture
def tmp_book(tmp_library):
    """Create a temporary book with source images and metadata."""
    book_dir = tmp_library / "test-book"
    book_dir.mkdir()

    # Create metadata
    metadata = {
        "title": "Test Book",
        "author": "Test Author",
        "year": 2024,
        "total_pages": 10,
        "scan_date": "2024-01-01"
    }
    with open(book_dir / "metadata.json", "w") as f:
        json.dump(metadata, f)

    # Create source directory with dummy PNG images
    source_dir = book_dir / "source"
    source_dir.mkdir()

    for i in range(1, 11):
        img = Image.new('RGB', (100, 100), color='white')
        img.save(source_dir / f"page_{i:04d}.png")

    return book_dir


@pytest.fixture
def book_storage(tmp_book, tmp_library):
    """Create a BookStorage instance for the temp book."""
    from infra.pipeline.storage.book_storage import BookStorage
    return BookStorage("test-book", storage_root=tmp_library)


@pytest.fixture
def stage_storage(book_storage):
    """Create a StageStorage instance for testing."""
    return book_storage.stage("test-stage")


@pytest.fixture
def library(tmp_library):
    """Create a Library instance with temp storage root."""
    from infra.pipeline.storage.library import Library
    return Library(storage_root=tmp_library)


@pytest.fixture
def metrics_file(tmp_path):
    """Create a temp path for metrics file."""
    return tmp_path / "metrics.json"


@pytest.fixture
def log_dir(tmp_path):
    """Create a temp directory for logs."""
    log_path = tmp_path / "logs"
    log_path.mkdir()
    return log_path
