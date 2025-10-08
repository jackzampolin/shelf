"""Tests for infra/checkpoint.py"""

import json
from pathlib import Path
from infra.checkpoint import CheckpointManager


def test_checkpoint_creation(tmp_path):
    """Test that checkpoint manager creates and saves checkpoint file."""
    checkpoint = CheckpointManager("test-scan", "ocr", storage_root=tmp_path)

    # Trigger a save by calling flush
    checkpoint.flush()

    checkpoint_file = tmp_path / "test-scan" / "checkpoints" / "ocr.json"
    assert checkpoint_file.exists()

    with open(checkpoint_file) as f:
        state = json.load(f)
        assert state["scan_id"] == "test-scan"
        assert state["stage"] == "ocr"
        assert state["status"] == "not_started"


def test_get_remaining_pages_fresh_start(tmp_path):
    """Test getting all pages on fresh start."""
    checkpoint = CheckpointManager("test-scan", "ocr", storage_root=tmp_path)

    remaining = checkpoint.get_remaining_pages(total_pages=10, resume=False)
    assert remaining == list(range(1, 11))


def test_mark_completed_and_resume(tmp_path):
    """Test marking pages complete and resuming from checkpoint."""
    # Create book structure
    book_dir = tmp_path / "test-scan"
    ocr_dir = book_dir / "ocr"
    ocr_dir.mkdir(parents=True)

    # Create some valid OCR outputs
    for page_num in [1, 2, 3]:
        page_file = ocr_dir / f"page_{page_num:04d}.json"
        page_file.write_text(json.dumps({
            "page_number": page_num,
            "regions": [{"text": "Test"}]
        }))

    checkpoint = CheckpointManager("test-scan", "ocr", storage_root=tmp_path)

    # Mark pages as completed
    for page_num in [1, 2, 3]:
        checkpoint.mark_completed(page_num)

    checkpoint.flush()  # Save checkpoint

    # New checkpoint manager (simulating restart)
    checkpoint2 = CheckpointManager("test-scan", "ocr", storage_root=tmp_path)

    # Resume should skip completed pages
    remaining = checkpoint2.get_remaining_pages(total_pages=5, resume=True)
    assert remaining == [4, 5]


def test_mark_stage_complete(tmp_path):
    """Test marking stage as complete."""
    checkpoint = CheckpointManager("test-scan", "correct", storage_root=tmp_path)

    checkpoint.get_remaining_pages(total_pages=10, resume=False)
    checkpoint.mark_stage_complete(metadata={"cost_usd": 5.25, "model": "gpt-4o-mini"})

    status = checkpoint.get_status()
    assert status["status"] == "completed"
    assert status["metadata"]["cost_usd"] == 5.25
    assert status["metadata"]["model"] == "gpt-4o-mini"


def test_progress_tracking(tmp_path):
    """Test that progress is calculated correctly."""
    checkpoint = CheckpointManager("test-scan", "correct", storage_root=tmp_path)

    checkpoint.get_remaining_pages(total_pages=100, resume=False)
    checkpoint.mark_completed(1)
    checkpoint.mark_completed(2)
    checkpoint.mark_completed(3)

    status = checkpoint.get_status()
    assert status["progress"]["completed"] == 3
    assert status["progress"]["remaining"] == 97
    assert status["progress"]["percent"] == 3.0
