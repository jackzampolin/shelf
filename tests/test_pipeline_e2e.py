"""
End-to-end pipeline tests.

Tests the complete OCR → Correct → Fix → Structure pipeline on real test data
with real API calls (no mocks).

Cost per run: ~$0.025 (5 pages through gpt-4o-mini + Claude)
"""

import pytest
import json
import shutil
from pathlib import Path
from tools.library import LibraryIndex


@pytest.fixture
def test_book_dir(tmp_path):
    """
    Create a temporary test book directory with fixture data.

    Copies the test_book fixture to a temporary location for testing.
    """
    fixture_dir = Path(__file__).parent / "fixtures" / "test_book"
    test_dir = tmp_path / "test-book"

    # Copy fixture to temp location
    shutil.copytree(fixture_dir, test_dir)

    return test_dir


@pytest.fixture
def test_library(tmp_path):
    """Create a temporary library for testing."""
    library_root = tmp_path / "book_scans"
    library_root.mkdir()

    # Create library.json
    library_data = {
        "version": "1.0",
        "last_updated": "2025-09-30T00:00:00",
        "books": {},
        "watch_dirs": [],
        "stats": {
            "total_books": 0,
            "total_scans": 0,
            "total_pages": 0,
            "total_cost_usd": 0.0
        }
    }

    library_file = library_root / "library.json"
    with open(library_file, 'w') as f:
        json.dump(library_data, f, indent=2)

    return LibraryIndex(storage_root=library_root)


@pytest.mark.e2e
@pytest.mark.api
@pytest.mark.slow
def test_full_pipeline_ocr_to_structure(test_book_dir, test_library, tmp_path):
    """
    Test complete pipeline: OCR → Correct → Fix → Structure.

    This test runs the entire pipeline on 5 test pages with real API calls.
    Verifies that:
    - All stages complete successfully
    - Output files are created in expected locations
    - Metadata tracking works
    - Costs are tracked correctly
    - Library syncs properly
    """
    from pipeline.run import BookPipeline

    # Setup: Copy test book to library location
    scan_id = "test-book"
    book_dir = test_library.storage_root / scan_id
    shutil.copytree(test_book_dir, book_dir)

    # Register in library
    test_library.add_book(
        title="The Accidental President (Test)",
        author="A. J. Baime",
        scan_id=scan_id,
        isbn="978-0544617346",
        notes="Test fixture"
    )

    # Run pipeline
    pipeline = BookPipeline(scan_id, storage_root=test_library.storage_root)
    success = pipeline.run(
        ocr_workers=4,
        correct_model="openai/gpt-4o-mini",
        correct_workers=5,
        correct_rate_limit=50,
        structure_model="anthropic/claude-sonnet-4.5"
    )

    # Assert: Pipeline completed successfully
    assert success, "Pipeline should complete successfully"

    # Assert: OCR outputs exist
    ocr_dir = book_dir / "ocr"
    assert ocr_dir.exists(), "OCR directory should exist"
    ocr_files = list(ocr_dir.glob("page_*.json"))
    assert len(ocr_files) == 5, f"Should have 5 OCR files, found {len(ocr_files)}"

    # Assert: Corrected outputs exist
    corrected_dir = book_dir / "corrected"
    assert corrected_dir.exists(), "Corrected directory should exist"
    corrected_files = list(corrected_dir.glob("page_*.json"))
    assert len(corrected_files) == 5, f"Should have 5 corrected files, found {len(corrected_files)}"

    # Assert: Each corrected file has LLM processing metadata
    for page_file in corrected_files:
        with open(page_file) as f:
            page_data = json.load(f)

        assert 'llm_processing' in page_data, f"{page_file.name} missing llm_processing"
        assert 'error_catalog' in page_data['llm_processing'], "Missing error_catalog"
        assert 'verification' in page_data['llm_processing'], "Missing verification"

    # Assert: Structured outputs exist
    structured_dir = book_dir / "structured"
    assert structured_dir.exists(), "Structured directory should exist"

    assert (structured_dir / "metadata.json").exists(), "Structure metadata should exist"
    assert (structured_dir / "full_book.md").exists(), "Full book markdown should exist"

    chapters_dir = structured_dir / "chapters"
    assert chapters_dir.exists(), "Chapters directory should exist"

    chunks_dir = structured_dir / "chunks"
    assert chunks_dir.exists(), "Chunks directory should exist"
    chunk_files = list(chunks_dir.glob("chunk_*.json"))
    assert len(chunk_files) > 0, "Should have chunk files"

    # Assert: Metadata has processing history
    metadata_file = book_dir / "metadata.json"
    assert metadata_file.exists(), "Scan metadata should exist"

    with open(metadata_file) as f:
        metadata = json.load(f)

    assert 'processing_history' in metadata, "Should have processing_history"

    # Check that all stages are recorded
    stages = [record['stage'] for record in metadata['processing_history']]
    assert 'ocr' in stages, "OCR stage should be recorded"
    assert 'correct' in stages, "Correct stage should be recorded"
    assert 'structure' in stages, "Structure stage should be recorded"

    # Assert: Costs are tracked
    total_cost = 0
    for record in metadata['processing_history']:
        cost = record.get('cost_usd', 0)
        assert cost >= 0, f"Cost should be non-negative, got {cost}"
        total_cost += cost

    # Should have some cost (correction + structure)
    assert total_cost > 0, f"Total cost should be positive, got {total_cost}"
    assert total_cost < 0.20, f"Total cost should be < $0.20, got ${total_cost:.4f}"

    # Assert: Library was synced
    test_library = LibraryIndex(storage_root=test_library.storage_root)
    scan_info = test_library.get_scan_info(scan_id)

    assert scan_info is not None, "Scan should be in library"
    assert scan_info['scan']['cost_usd'] > 0, "Library should have synced cost"
    assert scan_info['scan']['pages'] == 5, "Library should have correct page count"
    assert 'models' in scan_info['scan'], "Library should have model info"


@pytest.mark.e2e
@pytest.mark.api
def test_pipeline_handles_errors_gracefully(test_book_dir, test_library):
    """
    Test that pipeline handles pages with OCR errors correctly.

    Our test pages include difficult cases (page 5 had 0.00 confidence in real data).
    Verify the correction pipeline handles them without crashing.
    """
    from pipeline.run import BookPipeline

    # Setup
    scan_id = "test-errors"
    book_dir = test_library.storage_root / scan_id
    shutil.copytree(test_book_dir, book_dir)

    test_library.add_book(
        title="Test Errors",
        author="Test",
        scan_id=scan_id
    )

    # Run pipeline
    pipeline = BookPipeline(scan_id, storage_root=test_library.storage_root)
    success = pipeline.run(
        correct_model="openai/gpt-4o-mini",
        structure_model="anthropic/claude-sonnet-4.5"
    )

    # Should complete even with difficult pages
    assert success, "Pipeline should complete despite challenging pages"

    # All pages should be processed
    corrected_dir = book_dir / "corrected"
    corrected_files = list(corrected_dir.glob("page_*.json"))
    assert len(corrected_files) == 5, "All pages should be corrected"


@pytest.mark.e2e
def test_pipeline_creates_valid_json_outputs(test_book_dir, test_library):
    """
    Test that all pipeline outputs are valid JSON.

    Verifies no JSON parsing errors in any stage outputs.
    """
    from pipeline.run import BookPipeline

    # Setup
    scan_id = "test-json"
    book_dir = test_library.storage_root / scan_id
    shutil.copytree(test_book_dir, book_dir)

    test_library.add_book(
        title="Test JSON",
        author="Test",
        scan_id=scan_id
    )

    # Run pipeline
    pipeline = BookPipeline(scan_id, storage_root=test_library.storage_root)
    pipeline.run(
        correct_model="openai/gpt-4o-mini",
        structure_model="anthropic/claude-sonnet-4.5"
    )

    # Check all JSON files are valid
    json_files = []
    json_files.extend(book_dir.glob("**/*.json"))

    for json_file in json_files:
        try:
            with open(json_file) as f:
                json.load(f)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON in {json_file}: {e}")


@pytest.mark.e2e
@pytest.mark.api
def test_pipeline_text_quality_spot_check(test_book_dir, test_library):
    """
    Spot check text quality in corrected outputs.

    Verify that common words appear correctly (not OCR gibberish).
    This is a basic sanity check, not comprehensive quality assessment.
    """
    from pipeline.run import BookPipeline

    # Setup
    scan_id = "test-quality"
    book_dir = test_library.storage_root / scan_id
    shutil.copytree(test_book_dir, book_dir)

    test_library.add_book(
        title="Test Quality",
        author="Test",
        scan_id=scan_id
    )

    # Run pipeline
    pipeline = BookPipeline(scan_id, storage_root=test_library.storage_root)
    pipeline.run(
        correct_model="openai/gpt-4o-mini",
        structure_model="anthropic/claude-sonnet-4.5"
    )

    # Read full book markdown
    full_book = book_dir / "structured" / "full_book.md"
    assert full_book.exists(), "Full book markdown should exist"

    with open(full_book) as f:
        text = f.read()

    # Spot checks for expected content (from The Accidental President)
    # These should appear in our test pages
    assert len(text) > 1000, "Book text should be substantial"
    assert "Truman" in text or "President" in text or "Accidental" in text, \
        "Expected keywords should appear in text"

    # Check it's not mostly gibberish (has reasonable word-to-character ratio)
    words = text.split()
    assert len(words) > 100, "Should have substantial word count"
    avg_word_length = sum(len(w) for w in words) / len(words)
    assert 3 < avg_word_length < 10, f"Average word length should be reasonable, got {avg_word_length:.1f}"
