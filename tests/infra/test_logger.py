"""Tests for infra/logger.py"""

import json
from pathlib import Path
from infra.pipeline.logger import create_logger


def test_logger_creates_log_file(tmp_path):
    """Test that logger creates JSON log file."""
    log_dir = tmp_path / "logs"

    with create_logger("test-scan", "ocr", log_dir=log_dir, console_output=False) as logger:
        logger.info("Test message")

    # Check log file was created
    log_files = list(log_dir.glob("ocr_*.jsonl"))
    assert len(log_files) == 1

    # Check log content
    with open(log_files[0]) as f:
        log_entry = json.loads(f.readline())
        assert log_entry["message"] == "Test message"
        assert log_entry["scan_id"] == "test-scan"
        assert log_entry["stage"] == "ocr"


def test_logger_progress_tracking(tmp_path):
    """Test progress tracking with percentage calculation."""
    log_dir = tmp_path / "logs"

    with create_logger("test-scan", "correct", log_dir=log_dir, console_output=False) as logger:
        logger.progress("Processing pages", current=25, total=100)

    # Read log
    log_files = list(log_dir.glob("*.jsonl"))
    with open(log_files[0]) as f:
        log_entry = json.loads(f.readline())
        assert "progress" in log_entry
        assert log_entry["progress"]["current"] == 25
        assert log_entry["progress"]["total"] == 100
        assert log_entry["progress"]["percent"] == 25.0


def test_logger_multiple_messages(tmp_path):
    """Test that multiple log messages are written correctly."""
    log_dir = tmp_path / "logs"

    with create_logger("test-scan", "ocr", log_dir=log_dir, console_output=False) as logger:
        logger.info("First message")
        logger.info("Second message")
        logger.info("Third message")

    # Read all log entries
    log_files = list(log_dir.glob("*.jsonl"))
    with open(log_files[0]) as f:
        lines = f.readlines()
        assert len(lines) == 3

        # Verify all have proper structure
        for line in lines:
            log_entry = json.loads(line)
            assert "timestamp" in log_entry
            assert "level" in log_entry
            assert "message" in log_entry
            assert log_entry["scan_id"] == "test-scan"
            assert log_entry["stage"] == "ocr"


def test_logger_cost_tracking(tmp_path):
    """Test cost tracking in logs."""
    log_dir = tmp_path / "logs"

    with create_logger("test-scan", "correct", log_dir=log_dir, console_output=False) as logger:
        logger.cost("API call completed", cost_usd=0.05)

    log_files = list(log_dir.glob("*.jsonl"))
    with open(log_files[0]) as f:
        log_entry = json.loads(f.readline())
        assert log_entry["cost_usd"] == 0.05
