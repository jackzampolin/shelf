"""Tests for infra/checkpoint.py"""

import json
from pathlib import Path
from infra.pipeline.storage.checkpoint import CheckpointManager


def test_checkpoint_creation(tmp_path):
    """Test that checkpoint manager creates and saves checkpoint file."""
    checkpoint = CheckpointManager("test-scan", "ocr", storage_root=tmp_path)

    # Trigger a save by calling flush
    checkpoint.flush()

    checkpoint_file = tmp_path / "test-scan" / "ocr" / ".checkpoint"
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

    # Create some valid OCR outputs (must have "blocks" field for validation)
    for page_num in [1, 2, 3]:
        page_file = ocr_dir / f"page_{page_num:04d}.json"
        page_file.write_text(json.dumps({
            "page_number": page_num,
            "blocks": [{"text": "Test"}]  # Fixed: was "regions", should be "blocks"
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


def test_cost_accumulation(tmp_path):
    """Test that costs are accumulated correctly (only once per page)."""
    checkpoint = CheckpointManager("test-scan", "correction", storage_root=tmp_path)

    checkpoint.get_remaining_pages(total_pages=5, resume=False)

    # Mark pages complete with costs
    checkpoint.mark_completed(1, cost_usd=0.01)
    checkpoint.mark_completed(2, cost_usd=0.02)
    checkpoint.mark_completed(3, cost_usd=0.03)

    status = checkpoint.get_status()
    assert status["metadata"]["total_cost_usd"] == 0.06

    # Mark same page again (should NOT double-count cost)
    checkpoint.mark_completed(1, cost_usd=0.01)
    status = checkpoint.get_status()
    assert status["metadata"]["total_cost_usd"] == 0.06  # Still 0.06, not 0.07

    # Mark another new page
    checkpoint.mark_completed(4, cost_usd=0.04)
    status = checkpoint.get_status()
    assert status["metadata"]["total_cost_usd"] == 0.10  # 0.06 + 0.04


def test_cost_accumulation_on_retry(tmp_path):
    """Test that retrying a failed page doesn't double-count costs."""
    # Create book structure
    book_dir = tmp_path / "test-scan"
    corrected_dir = book_dir / "corrected"
    corrected_dir.mkdir(parents=True)

    checkpoint = CheckpointManager("test-scan", "correction", storage_root=tmp_path, output_dir="corrected")
    checkpoint.get_remaining_pages(total_pages=5, resume=False)

    # Process pages 1, 2, 3 successfully
    for page_num in [1, 2, 3]:
        # Create valid output
        page_file = corrected_dir / f"page_{page_num:04d}.json"
        page_file.write_text(json.dumps({
            "page_number": page_num,
            "blocks": [{"text": "Test"}]
        }))
        checkpoint.mark_completed(page_num, cost_usd=0.01)

    status = checkpoint.get_status()
    assert status["metadata"]["total_cost_usd"] == 0.03

    # Simulate a retry scenario: new checkpoint manager (restart)
    checkpoint2 = CheckpointManager("test-scan", "correction", storage_root=tmp_path, output_dir="corrected")
    remaining = checkpoint2.get_remaining_pages(total_pages=5, resume=True)

    # Should only get pages 4, 5 (1, 2, 3 already done)
    assert remaining == [4, 5]

    # Process remaining pages
    for page_num in [4, 5]:
        page_file = corrected_dir / f"page_{page_num:04d}.json"
        page_file.write_text(json.dumps({
            "page_number": page_num,
            "blocks": [{"text": "Test"}]
        }))
        checkpoint2.mark_completed(page_num, cost_usd=0.01)

    status = checkpoint2.get_status()
    # Total should be 0.05 (3 pages at 0.01 + 2 pages at 0.01), NOT 0.06 from double-counting
    assert status["metadata"]["total_cost_usd"] == 0.05


def test_concurrent_cost_accumulation(tmp_path):
    """Test that concurrent cost accumulation is thread-safe."""
    import threading

    checkpoint = CheckpointManager("test-scan", "correction", storage_root=tmp_path)
    checkpoint.get_remaining_pages(total_pages=100, resume=False)

    # Simulate concurrent workers marking pages complete with costs
    def mark_pages(start, end, cost_per_page):
        for page_num in range(start, end):
            checkpoint.mark_completed(page_num, cost_usd=cost_per_page)

    threads = []
    # 10 threads, each processing 10 pages at $0.01 each
    for i in range(10):
        t = threading.Thread(
            target=mark_pages,
            args=(i * 10 + 1, i * 10 + 11, 0.01)
        )
        threads.append(t)
        t.start()

    # Wait for all threads
    for t in threads:
        t.join()

    status = checkpoint.get_status()
    # 100 pages at $0.01 each = $1.00 (use round to avoid floating point precision issues)
    assert status["progress"]["completed"] == 100
    assert round(status["metadata"]["total_cost_usd"], 2) == 1.00
