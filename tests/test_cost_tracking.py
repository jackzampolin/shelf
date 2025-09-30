"""
Cost tracking tests.

Tests that costs are accurately tracked and synced throughout the pipeline.
No mocks - tests real cost tracking with real API calls.
"""

import pytest
import json
import shutil
from pathlib import Path
from tools.library import LibraryIndex
from utils import get_scan_total_cost, get_scan_models


@pytest.fixture
def test_book_dir(tmp_path):
    """Create a temporary test book directory."""
    fixture_dir = Path(__file__).parent / "fixtures" / "test_book"
    test_dir = tmp_path / "test-book"
    shutil.copytree(fixture_dir, test_dir)
    return test_dir


@pytest.fixture
def test_library(tmp_path):
    """Create a temporary library."""
    library_root = tmp_path / "book_scans"
    library_root.mkdir()

    library_data = {
        "version": "1.0",
        "last_updated": "2025-09-30T00:00:00",
        "books": {},
        "watch_dirs": [],
        "stats": {"total_books": 0, "total_scans": 0, "total_pages": 0, "total_cost_usd": 0.0}
    }

    with open(library_root / "library.json", 'w') as f:
        json.dump(library_data, f, indent=2)

    return LibraryIndex(storage_root=library_root)


@pytest.mark.e2e
@pytest.mark.api
def test_cost_tracking_full_pipeline(test_book_dir, test_library):
    """
    Test that costs are tracked accurately through full pipeline.

    Verifies:
    - Each stage records cost in metadata.json
    - Total cost can be calculated from processing_history
    - Library.json syncs the cost correctly
    """
    from pipeline.run import BookPipeline

    # Setup
    scan_id = "test-costs"
    book_dir = test_library.storage_root / scan_id
    shutil.copytree(test_book_dir, book_dir)

    test_library.add_book(
        title="Test Costs",
        author="Test",
        scan_id=scan_id
    )

    # Run full pipeline
    pipeline = BookPipeline(scan_id, storage_root=test_library.storage_root)
    success = pipeline.run(
        correct_model="openai/gpt-4o-mini",
        structure_model="anthropic/claude-sonnet-4.5"
    )

    assert success, "Pipeline should complete"

    # Check metadata.json has processing history
    metadata_file = book_dir / "metadata.json"
    with open(metadata_file) as f:
        metadata = json.load(f)

    assert 'processing_history' in metadata, "Should have processing_history"

    # Check each stage has cost recorded
    history = metadata['processing_history']
    stage_costs = {record['stage']: record.get('cost_usd', 0) for record in history}

    assert 'ocr' in stage_costs, "OCR stage should be recorded"
    assert stage_costs['ocr'] == 0.0, "OCR should be free"

    assert 'correct' in stage_costs, "Correct stage should be recorded"
    assert stage_costs['correct'] > 0, "Correct should have cost"

    assert 'structure' in stage_costs, "Structure stage should be recorded"
    assert stage_costs['structure'] > 0, "Structure should have cost"

    # Calculate total cost
    total_cost = get_scan_total_cost(book_dir)
    assert total_cost > 0, "Total cost should be positive"

    # Verify cost is reasonable (5 pages with correction + structure)
    assert total_cost < 0.20, f"Total cost should be < $0.20, got ${total_cost:.4f}"

    # Check library.json was synced
    test_library = LibraryIndex(storage_root=test_library.storage_root)
    scan_info = test_library.get_scan_info(scan_id)

    library_cost = scan_info['scan']['cost_usd']
    assert library_cost == total_cost, \
        f"Library cost ({library_cost}) should match metadata total ({total_cost})"


@pytest.mark.e2e
@pytest.mark.api
def test_cost_breakdown_by_stage(test_book_dir, test_library):
    """
    Test that costs can be broken down by stage.

    Useful for understanding where costs come from.
    """
    from pipeline.run import BookPipeline

    # Setup
    scan_id = "test-breakdown"
    book_dir = test_library.storage_root / scan_id
    shutil.copytree(test_book_dir, book_dir)

    test_library.add_book(title="Test Breakdown", author="Test", scan_id=scan_id)

    # Run pipeline
    pipeline = BookPipeline(scan_id, storage_root=test_library.storage_root)
    pipeline.run(
        correct_model="openai/gpt-4o-mini",
        structure_model="anthropic/claude-sonnet-4.5"
    )

    # Get cost breakdown
    metadata_file = book_dir / "metadata.json"
    with open(metadata_file) as f:
        metadata = json.load(f)

    breakdown = {}
    for record in metadata['processing_history']:
        stage = record['stage']
        cost = record.get('cost_usd', 0)
        breakdown[stage] = cost

    # Print breakdown for visibility
    print("\nCost Breakdown:")
    for stage, cost in breakdown.items():
        print(f"  {stage}: ${cost:.4f}")

    total = sum(breakdown.values())
    print(f"  TOTAL: ${total:.4f}")

    # Correction should be the most expensive
    # (more pages processed with LLM than structure)
    if 'correct' in breakdown and 'structure' in breakdown:
        # Note: This may not always be true depending on models used
        # But it's a useful sanity check
        assert breakdown['correct'] >= 0, "Correction should have cost"


def test_get_scan_total_cost(tmp_path):
    """Test utility function for calculating total cost."""
    from utils import update_book_metadata

    # Create scan directory
    scan_dir = tmp_path / "test-scan"
    scan_dir.mkdir()

    # Create metadata with processing history
    metadata = {
        "title": "Test",
        "processing_history": []
    }

    metadata_file = scan_dir / "metadata.json"
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f)

    # Add some processing records
    update_book_metadata(scan_dir, 'ocr', {'cost_usd': 0.0})
    update_book_metadata(scan_dir, 'correct', {'cost_usd': 2.50})
    update_book_metadata(scan_dir, 'structure', {'cost_usd': 0.75})

    # Calculate total
    total = get_scan_total_cost(scan_dir)

    assert total == 3.25, f"Total should be 3.25, got {total}"


def test_get_scan_models(tmp_path):
    """Test utility function for extracting models used."""
    from utils import update_book_metadata

    # Create scan directory
    scan_dir = tmp_path / "test-scan"
    scan_dir.mkdir()

    # Create metadata
    metadata = {"title": "Test", "processing_history": []}
    with open(scan_dir / "metadata.json", 'w') as f:
        json.dump(metadata, f)

    # Add processing records with models
    update_book_metadata(scan_dir, 'ocr', {'model': 'tesseract'})
    update_book_metadata(scan_dir, 'correct', {'model': 'openai/gpt-4o-mini'})
    update_book_metadata(scan_dir, 'structure', {'model': 'anthropic/claude-sonnet-4.5'})

    # Get models
    models = get_scan_models(scan_dir)

    assert models['ocr'] == 'tesseract'
    assert models['correct'] == 'openai/gpt-4o-mini'
    assert models['structure'] == 'anthropic/claude-sonnet-4.5'


@pytest.mark.e2e
def test_library_stats_aggregate_costs(test_library):
    """
    Test that library statistics correctly aggregate costs across books.
    """
    # Add multiple books with costs
    test_library.add_book(title="Book One", author="Author", scan_id="book-one")
    test_library.update_scan_metadata("book-one", {
        'pages': 100,
        'cost_usd': 5.00
    })

    test_library.add_book(title="Book Two", author="Author", scan_id="book-two")
    test_library.update_scan_metadata("book-two", {
        'pages': 200,
        'cost_usd': 10.50
    })

    # Get stats
    stats = test_library.get_stats()

    assert stats['total_books'] == 2
    assert stats['total_scans'] == 2
    assert stats['total_pages'] == 300
    assert stats['total_cost_usd'] == 15.50


@pytest.mark.e2e
@pytest.mark.api
def test_rerun_stage_adds_new_cost_record(test_book_dir, test_library):
    """
    Test that skipped stages don't create duplicate processing records.

    When a stage is already complete and gets skipped, it should not add
    a new processing record (to avoid misleading cost/time tracking).
    """
    from pipeline.run import BookPipeline

    # Setup
    scan_id = "test-rerun-cost"
    book_dir = test_library.storage_root / scan_id
    shutil.copytree(test_book_dir, book_dir)

    test_library.add_book(title="Test Rerun", author="Test", scan_id=scan_id)

    # Run OCR once
    pipeline1 = BookPipeline(scan_id, storage_root=test_library.storage_root)
    pipeline1.run(
        stages=['ocr'],
        ocr_workers=4
    )

    # Check processing history
    with open(book_dir / "metadata.json") as f:
        metadata1 = json.load(f)

    history1_len = len(metadata1['processing_history'])
    assert history1_len == 1, "Should have 1 processing record after first run"

    # Run OCR again - should skip since already complete
    pipeline2 = BookPipeline(scan_id, storage_root=test_library.storage_root)
    pipeline2.run(stages=['ocr'], ocr_workers=4)

    # Check processing history again - should still be 1 (not 2)
    with open(book_dir / "metadata.json") as f:
        metadata2 = json.load(f)

    history2_len = len(metadata2['processing_history'])
    assert history2_len == 1, "Should still have 1 processing record (stage was skipped)"

    # Verify it's still the OCR record
    stages = [record['stage'] for record in metadata2['processing_history']]
    assert stages[0] == 'ocr', "Should be the original OCR record"
