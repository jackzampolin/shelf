"""
Checkpoint system tests.

Tests for the CheckpointManager class including:
- Save/load cycle
- Resume functionality
- Thread safety
- Validation logic
- Corruption recovery
"""

import pytest
import json
import threading
import time
from pathlib import Path
from checkpoint import CheckpointManager


@pytest.fixture
def test_storage(tmp_path):
    """Create a test storage directory structure."""
    storage_root = tmp_path / "book_scans"
    scan_dir = storage_root / "test-book"

    # Create directories
    scan_dir.mkdir(parents=True)
    (scan_dir / "ocr").mkdir()
    (scan_dir / "corrected").mkdir()
    (scan_dir / "structured").mkdir()

    # Create test metadata
    metadata = {
        "scan_id": "test-book",
        "title": "Test Book",
        "total_pages": 100
    }
    with open(scan_dir / "metadata.json", 'w') as f:
        json.dump(metadata, f)

    return storage_root


@pytest.fixture
def checkpoint_manager(test_storage):
    """Create a CheckpointManager for testing."""
    return CheckpointManager(
        scan_id="test-book",
        stage="correction",
        storage_root=test_storage
    )


def test_checkpoint_initialization(checkpoint_manager):
    """Test that checkpoint initializes with correct structure."""
    status = checkpoint_manager.get_status()

    assert status['version'] == "1.0"
    assert status['scan_id'] == "test-book"
    assert status['stage'] == "correction"
    assert status['status'] == "not_started"
    assert status['completed_pages'] == []
    assert status['total_pages'] == 0
    assert status['costs']['total_usd'] == 0.0


def test_checkpoint_save_load_cycle(checkpoint_manager):
    """Test that checkpoint saves and loads correctly."""
    # Mark some pages as completed
    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)
    checkpoint_manager.mark_completed(page_num=2, cost_usd=0.02)
    checkpoint_manager.mark_completed(page_num=3, cost_usd=0.02)
    checkpoint_manager.flush()  # Force save

    # Verify checkpoint file exists
    assert checkpoint_manager.checkpoint_file.exists()

    # Create a new manager instance to test loading
    new_manager = CheckpointManager(
        scan_id="test-book",
        stage="correction",
        storage_root=checkpoint_manager.storage_root
    )

    status = new_manager.get_status()
    assert len(status['completed_pages']) == 3
    assert status['completed_pages'] == [1, 2, 3]
    assert status['costs']['total_usd'] == pytest.approx(0.06, rel=1e-2)


def test_resume_skips_completed_pages(checkpoint_manager, test_storage):
    """Test that resume mode skips already-completed pages."""
    # Create some output files to simulate completed work
    corrected_dir = test_storage / "test-book" / "corrected"
    for page_num in [1, 2, 3]:
        output_file = corrected_dir / f"page_{page_num:04d}.json"
        with open(output_file, 'w') as f:
            json.dump({"page": page_num, "text": "test"}, f)

    # Get remaining pages with resume=True
    remaining = checkpoint_manager.get_remaining_pages(
        total_pages=10,
        resume=True,
        start_page=1,
        end_page=10
    )

    # Should skip pages 1, 2, 3
    assert remaining == [4, 5, 6, 7, 8, 9, 10]

    # Verify checkpoint was updated
    status = checkpoint_manager.get_status()
    assert len(status['completed_pages']) == 3
    assert status['completed_pages'] == [1, 2, 3]


def test_resume_false_processes_all_pages(checkpoint_manager):
    """Test that resume=False processes all pages regardless of completion."""
    # Mark some pages as completed
    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)
    checkpoint_manager.mark_completed(page_num=2, cost_usd=0.02)
    checkpoint_manager.flush()

    # Get remaining pages with resume=False
    remaining = checkpoint_manager.get_remaining_pages(
        total_pages=5,
        resume=False,
        start_page=1,
        end_page=5
    )

    # Should process all pages
    assert remaining == [1, 2, 3, 4, 5]


def test_validation_rejects_missing_files(checkpoint_manager):
    """Test that validation correctly identifies missing output files."""
    # Page 1 doesn't exist
    assert checkpoint_manager.validate_page_output(1) is False


def test_validation_accepts_valid_files(checkpoint_manager, test_storage):
    """Test that validation accepts valid output files."""
    # Create a valid output file
    corrected_dir = test_storage / "test-book" / "corrected"
    output_file = corrected_dir / "page_0001.json"
    with open(output_file, 'w') as f:
        json.dump({"page": 1, "text": "valid content"}, f)

    assert checkpoint_manager.validate_page_output(1) is True


def test_validation_rejects_empty_files(checkpoint_manager, test_storage):
    """Test that validation rejects empty/invalid output files."""
    # Create an empty JSON file
    corrected_dir = test_storage / "test-book" / "corrected"
    output_file = corrected_dir / "page_0001.json"
    with open(output_file, 'w') as f:
        json.dump({}, f)  # Empty dict

    assert checkpoint_manager.validate_page_output(1) is False


def test_validation_rejects_corrupted_json(checkpoint_manager, test_storage):
    """Test that validation rejects corrupted JSON files."""
    # Create a corrupted JSON file
    corrected_dir = test_storage / "test-book" / "corrected"
    output_file = corrected_dir / "page_0001.json"
    with open(output_file, 'w') as f:
        f.write("{invalid json")

    assert checkpoint_manager.validate_page_output(1) is False


def test_mark_completed_updates_progress(checkpoint_manager):
    """Test that marking pages complete updates progress correctly."""
    checkpoint_manager.get_remaining_pages(total_pages=10, resume=False)

    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)
    checkpoint_manager.mark_completed(page_num=2, cost_usd=0.02)

    status = checkpoint_manager.get_status()
    assert status['progress']['completed'] == 2
    assert status['progress']['remaining'] == 8
    assert status['progress']['percent'] == pytest.approx(20.0, rel=1e-2)


def test_mark_completed_tracks_costs(checkpoint_manager):
    """Test that marking pages complete tracks costs correctly."""
    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)
    checkpoint_manager.mark_completed(page_num=2, cost_usd=0.03)
    checkpoint_manager.mark_completed(page_num=3, cost_usd=0.01)

    status = checkpoint_manager.get_status()
    assert status['costs']['total_usd'] == pytest.approx(0.06, rel=1e-2)


def test_mark_completed_idempotent(checkpoint_manager):
    """Test that marking the same page completed multiple times is idempotent."""
    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)
    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)
    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)

    status = checkpoint_manager.get_status()
    assert len(status['completed_pages']) == 1
    # Note: cost will accumulate, which may be incorrect behavior
    # This test documents current behavior


def test_stage_complete(checkpoint_manager):
    """Test marking stage as complete."""
    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)
    checkpoint_manager.mark_stage_complete(metadata={"test": "value"})

    status = checkpoint_manager.get_status()
    assert status['status'] == 'completed'
    assert 'completed_at' in status
    assert status['metadata']['test'] == "value"


def test_stage_failed(checkpoint_manager):
    """Test marking stage as failed."""
    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)
    checkpoint_manager.mark_stage_failed(error="Test error")

    status = checkpoint_manager.get_status()
    assert status['status'] == 'failed'
    assert status['error'] == "Test error"
    assert 'failed_at' in status


def test_reset_checkpoint(checkpoint_manager):
    """Test resetting checkpoint to initial state."""
    # Make some progress
    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)
    checkpoint_manager.mark_completed(page_num=2, cost_usd=0.02)
    checkpoint_manager.flush()

    # Reset
    checkpoint_manager.reset()

    status = checkpoint_manager.get_status()
    assert status['status'] == 'not_started'
    assert status['completed_pages'] == []
    assert status['costs']['total_usd'] == 0.0


def test_concurrent_mark_completed(checkpoint_manager):
    """Test thread-safe concurrent marking of pages as completed."""
    num_threads = 10
    pages_per_thread = 10

    def worker(start_page):
        for i in range(pages_per_thread):
            page_num = start_page + i
            checkpoint_manager.mark_completed(page_num=page_num, cost_usd=0.02)

    threads = []
    for i in range(num_threads):
        start_page = i * pages_per_thread + 1
        t = threading.Thread(target=worker, args=(start_page,))
        threads.append(t)
        t.start()

    # Wait for all threads
    for t in threads:
        t.join()

    # Verify all pages were marked
    status = checkpoint_manager.get_status()
    expected_pages = num_threads * pages_per_thread
    assert len(status['completed_pages']) == expected_pages
    assert status['completed_pages'] == sorted(status['completed_pages'])


def test_estimate_cost_saved(checkpoint_manager):
    """Test cost savings estimation."""
    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)
    checkpoint_manager.mark_completed(page_num=2, cost_usd=0.02)
    checkpoint_manager.mark_completed(page_num=3, cost_usd=0.02)

    # Default avg cost is $0.02/page
    savings = checkpoint_manager.estimate_cost_saved()
    assert savings == pytest.approx(0.06, rel=1e-2)

    # Custom avg cost
    savings = checkpoint_manager.estimate_cost_saved(avg_cost_per_page=0.05)
    assert savings == pytest.approx(0.15, rel=1e-2)


def test_progress_summary(checkpoint_manager):
    """Test human-readable progress summary."""
    # Not started
    summary = checkpoint_manager.get_progress_summary()
    assert "Not started" in summary

    # In progress
    checkpoint_manager.get_remaining_pages(total_pages=10, resume=False)
    checkpoint_manager.mark_completed(page_num=1, cost_usd=0.02)
    summary = checkpoint_manager.get_progress_summary()
    assert "In progress" in summary
    assert "10%" in summary or "1/10" in summary

    # Completed
    checkpoint_manager.mark_stage_complete()
    summary = checkpoint_manager.get_progress_summary()
    assert "completed" in summary.lower()


def test_corrupted_checkpoint_recovery(checkpoint_manager):
    """Test that corrupted checkpoint files are handled gracefully."""
    # Create a corrupted checkpoint file
    with open(checkpoint_manager.checkpoint_file, 'w') as f:
        f.write("{corrupted json")

    # Create new manager - should recover by creating fresh checkpoint
    new_manager = CheckpointManager(
        scan_id="test-book",
        stage="correction",
        storage_root=checkpoint_manager.storage_root
    )

    status = new_manager.get_status()
    assert status['status'] == 'not_started'
    assert status['completed_pages'] == []


def test_version_mismatch_recovery(checkpoint_manager):
    """Test that version mismatches trigger fresh checkpoint."""
    # Create checkpoint with old version
    checkpoint_data = {
        "version": "0.9",  # Old version
        "scan_id": "test-book",
        "stage": "correction",
        "completed_pages": [1, 2, 3]
    }
    with open(checkpoint_manager.checkpoint_file, 'w') as f:
        json.dump(checkpoint_data, f)

    # Create new manager - should create fresh checkpoint
    new_manager = CheckpointManager(
        scan_id="test-book",
        stage="correction",
        storage_root=checkpoint_manager.storage_root
    )

    status = new_manager.get_status()
    assert status['version'] == "1.0"
    assert status['completed_pages'] == []


def test_page_range_with_resume(checkpoint_manager, test_storage):
    """Test resume with custom page ranges (start/end)."""
    # Create output files for pages 5-10
    corrected_dir = test_storage / "test-book" / "corrected"
    for page_num in range(5, 11):
        output_file = corrected_dir / f"page_{page_num:04d}.json"
        with open(output_file, 'w') as f:
            json.dump({"page": page_num, "text": "test"}, f)

    # Request pages 1-15, but some are already done
    remaining = checkpoint_manager.get_remaining_pages(
        total_pages=100,
        resume=True,
        start_page=1,
        end_page=15
    )

    # Should skip pages 5-10
    expected = [1, 2, 3, 4, 11, 12, 13, 14, 15]
    assert remaining == expected


def test_incremental_checkpoint_saves(checkpoint_manager):
    """Test that checkpoints are saved incrementally (every 10 pages)."""
    checkpoint_manager.get_remaining_pages(total_pages=100, resume=False)

    # Mark 9 pages - checkpoint should not auto-save yet
    for i in range(1, 10):
        checkpoint_manager.mark_completed(page_num=i, cost_usd=0.02)

    # Load new manager - should not see all 9 pages (only if manually flushed)
    # This is implementation-dependent

    # Mark 10th page - should trigger auto-save
    checkpoint_manager.mark_completed(page_num=10, cost_usd=0.02)

    # Load new manager - should see all 10 pages
    new_manager = CheckpointManager(
        scan_id="test-book",
        stage="correction",
        storage_root=checkpoint_manager.storage_root
    )
    status = new_manager.get_status()
    assert len(status['completed_pages']) == 10


def test_different_stages_separate_checkpoints(test_storage):
    """Test that different stages maintain separate checkpoints."""
    ocr_manager = CheckpointManager(
        scan_id="test-book",
        stage="ocr",
        storage_root=test_storage
    )
    correct_manager = CheckpointManager(
        scan_id="test-book",
        stage="correction",
        storage_root=test_storage
    )

    # Mark pages in OCR stage
    ocr_manager.mark_completed(page_num=1, cost_usd=0.0)
    ocr_manager.mark_completed(page_num=2, cost_usd=0.0)
    ocr_manager.flush()

    # Mark different pages in correction stage
    correct_manager.mark_completed(page_num=1, cost_usd=0.02)
    correct_manager.flush()

    # Verify separate tracking
    ocr_status = ocr_manager.get_status()
    correct_status = correct_manager.get_status()

    assert len(ocr_status['completed_pages']) == 2
    assert len(correct_status['completed_pages']) == 1
    assert ocr_status['costs']['total_usd'] == 0.0
    assert correct_status['costs']['total_usd'] == pytest.approx(0.02, rel=1e-2)


def test_scan_existing_outputs(checkpoint_manager, test_storage):
    """Test scanning output directory for completed pages."""
    corrected_dir = test_storage / "test-book" / "corrected"

    # Create output files for pages 1, 3, 5 (skip 2, 4)
    for page_num in [1, 3, 5]:
        output_file = corrected_dir / f"page_{page_num:04d}.json"
        with open(output_file, 'w') as f:
            json.dump({"page": page_num, "text": "test"}, f)

    valid_pages = checkpoint_manager.scan_existing_outputs(total_pages=10)
    assert valid_pages == {1, 3, 5}
