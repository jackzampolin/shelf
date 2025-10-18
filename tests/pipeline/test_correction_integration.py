"""
Integration tests for correction stage using real book data.

These tests use actual book data fixtures (pages 5-15 from accidental-president)
stored in tests/fixtures/ and make real LLM API calls.

Requires OPENROUTER_API_KEY environment variable to run.

Run with: pytest tests/pipeline/test_correction_integration.py -v -s -m integration
"""

import os
import sys
import json
import shutil
import pytest
import importlib
from pathlib import Path
from dotenv import load_dotenv

# Load .env file before checking for API key
load_dotenv()

# Skip all tests in this file if no API key
pytestmark = pytest.mark.skipif(
    not os.getenv('OPENROUTER_API_KEY'),
    reason="OPENROUTER_API_KEY not set - skipping integration tests"
)


@pytest.fixture
def real_book_data(tmp_path):
    """
    Copy fixture book data to tmp directory for testing.

    Uses data from tests/fixtures/accidental-president/ (pages 5-15, renumbered 1-11).
    Returns a prepared BookStorage-compatible directory structure.
    """
    # Source fixture data
    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "accidental-president"

    if not fixtures_dir.exists():
        pytest.skip("Fixture data not found in tests/fixtures/accidental-president/")

    # Create test book in tmp
    test_book = tmp_path / "test-book"
    test_book.mkdir()

    # Copy metadata
    source_metadata = fixtures_dir / "metadata.json"
    shutil.copy2(source_metadata, test_book / "metadata.json")

    # Copy OCR and source data
    test_ocr = test_book / "ocr"
    test_source = test_book / "source"

    shutil.copytree(fixtures_dir / "ocr", test_ocr)
    shutil.copytree(fixtures_dir / "source", test_source)

    # Count pages
    page_count = len(list(test_ocr.glob("page_*.json")))

    return {
        'book_dir': test_book,
        'storage_root': tmp_path,
        'scan_id': 'test-book',
        'page_count': page_count
    }


@pytest.mark.slow
@pytest.mark.integration
def test_correction_stage_real_data(real_book_data):
    """
    Integration test: Run correction stage on real book data with actual LLM calls.

    This test verifies:
    - Correction stage processes real pages successfully
    - Output files are created with correct structure
    - Schema validation passes
    - Metadata is updated correctly
    """
    # Import VisionCorrector using importlib (can't use `from pipeline.2_correction`)
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    correction_module = importlib.import_module('pipeline.2_correction')
    VisionCorrector = correction_module.VisionCorrector

    from infra.storage.book_storage import BookStorage

    # Initialize corrector with minimal workers for testing
    corrector = VisionCorrector(
        storage_root=real_book_data['storage_root'],
        max_workers=2,  # Keep it slow for testing
        enable_checkpoints=True
    )

    # Run correction
    print(f"\nProcessing {real_book_data['page_count']} pages from accidental-president...")
    corrector.process_book(real_book_data['scan_id'], resume=False)

    # Verify results
    storage = BookStorage(
        scan_id=real_book_data['scan_id'],
        storage_root=real_book_data['storage_root']
    )

    # Check corrected files were created
    corrected_pages = storage.correction.list_output_pages()
    assert len(corrected_pages) == real_book_data['page_count'], \
        f"Expected {real_book_data['page_count']} corrected pages, got {len(corrected_pages)}"

    # Verify each corrected page has valid structure
    for page_file in corrected_pages:
        with open(page_file, 'r') as f:
            correction_data = json.load(f)

        # Check required fields
        assert 'page_number' in correction_data
        assert 'blocks' in correction_data
        assert 'model_used' in correction_data
        assert 'processing_cost' in correction_data
        assert 'timestamp' in correction_data
        assert 'total_blocks' in correction_data
        assert 'total_corrections' in correction_data
        assert 'avg_confidence' in correction_data

        # Verify blocks structure
        assert isinstance(correction_data['blocks'], list)
        assert len(correction_data['blocks']) > 0, "Page should have at least one block"

        for block in correction_data['blocks']:
            assert 'block_num' in block
            assert 'paragraphs' in block
            assert isinstance(block['paragraphs'], list)

            for para in block['paragraphs']:
                assert 'par_num' in para
                assert 'text' in para  # Can be null
                assert 'notes' in para  # Can be null
                assert 'confidence' in para
                assert 0.0 <= para['confidence'] <= 1.0

    # Verify metadata was updated
    metadata = storage.load_metadata()
    assert metadata.get('correction_complete') is True
    assert 'correction_completion_date' in metadata
    assert 'correction_total_cost' in metadata
    assert metadata['correction_total_cost'] > 0  # Should have incurred some cost

    # Verify checkpoint
    checkpoint_file = storage.checkpoint_file('correction')
    assert checkpoint_file.exists()

    with open(checkpoint_file, 'r') as f:
        checkpoint_data = json.load(f)

    assert checkpoint_data['status'] == 'completed'
    assert checkpoint_data['total_pages'] == real_book_data['page_count']
    assert len(checkpoint_data['completed_pages']) == real_book_data['page_count']

    print(f"\n✅ Integration test passed!")
    print(f"   Processed: {real_book_data['page_count']} pages")
    print(f"   Total cost: ${metadata['correction_total_cost']:.4f}")
    print(f"   Avg per page: ${metadata['correction_total_cost']/real_book_data['page_count']:.4f}")


@pytest.mark.slow
@pytest.mark.integration
def test_correction_stage_resume(real_book_data):
    """
    Integration test: Verify checkpoint resume works correctly.

    Process a few pages, interrupt, then resume and verify completion.
    """
    # Import VisionCorrector using importlib
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    correction_module = importlib.import_module('pipeline.2_correction')
    VisionCorrector = correction_module.VisionCorrector

    from infra.storage.book_storage import BookStorage

    storage = BookStorage(
        scan_id=real_book_data['scan_id'],
        storage_root=real_book_data['storage_root']
    )

    # First run: Process only first 3 pages by manually creating checkpoint
    corrector = VisionCorrector(
        storage_root=real_book_data['storage_root'],
        max_workers=1,
        enable_checkpoints=True
    )

    # Manually process just first 3 pages to simulate partial completion
    # (In real scenario, we'd interrupt mid-process, but for testing we'll manually control it)

    # Process first 3 pages
    print(f"\nProcessing first 3 pages...")

    # Create checkpoint directory
    storage.checkpoints_dir.mkdir(exist_ok=True)

    # Manually mark first 3 pages as completed in checkpoint
    checkpoint_file = storage.checkpoint_file('correction')
    checkpoint_data = {
        'stage': 'correction',
        'status': 'in_progress',
        'total_pages': real_book_data['page_count'],
        'completed_pages': [1, 2, 3],
        'metadata': {
            'total_cost_usd': 0.15  # Fake cost for 3 pages
        }
    }
    with open(checkpoint_file, 'w') as f:
        json.dump(checkpoint_data, f, indent=2)

    # Create fake correction files for first 3 pages
    storage.correction.ensure_directories()
    for page_num in [1, 2, 3]:
        fake_correction = {
            'page_number': page_num,
            'blocks': [{'block_num': 1, 'paragraphs': [{'par_num': 1, 'text': None, 'notes': 'Fake', 'confidence': 1.0}]}],
            'model_used': 'test',
            'processing_cost': 0.05,
            'timestamp': '2024-01-01T00:00:00',
            'total_blocks': 1,
            'total_corrections': 0,
            'avg_confidence': 1.0
        }
        with open(storage.correction.output_page(page_num), 'w') as f:
            json.dump(fake_correction, f, indent=2)

    # Now resume and process remaining pages
    print(f"Resuming to process remaining {real_book_data['page_count'] - 3} pages...")
    corrector.process_book(real_book_data['scan_id'], resume=True)

    # Verify all pages were processed
    corrected_pages = storage.correction.list_output_pages()
    assert len(corrected_pages) == real_book_data['page_count']

    # Verify checkpoint shows completion
    with open(checkpoint_file, 'r') as f:
        final_checkpoint = json.load(f)

    assert final_checkpoint['status'] == 'completed'
    assert len(final_checkpoint['completed_pages']) == real_book_data['page_count']

    print(f"\n✅ Resume test passed!")
    print(f"   Initial: 3 pages (fake)")
    print(f"   Resumed: {real_book_data['page_count'] - 3} pages (real)")
    print(f"   Total: {real_book_data['page_count']} pages")
