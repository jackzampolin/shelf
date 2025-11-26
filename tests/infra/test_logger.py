"""
Tests for infra/pipeline/logger.py

Key behaviors to verify:
1. Lazy initialization - no files created until first log
2. Single append-only file per stage (no timestamps in filename)
3. JSON formatting with proper fields
4. Multiple log levels work
5. Close doesn't create files if nothing was logged
"""

import json
from pathlib import Path

from infra.pipeline.logger import PipelineLogger, create_logger


class TestPipelineLoggerLazyInit:
    """Test that logger initializes lazily."""

    def test_no_file_created_on_init(self, tmp_path):
        """Logger should not create any files on instantiation."""
        log_dir = tmp_path / "logs"

        logger = PipelineLogger(
            scan_id="test-book",
            stage="test-stage",
            log_dir=log_dir
        )

        # Directory should not exist yet
        assert not log_dir.exists(), "Log directory should not be created on init"
        # Log file should not exist
        assert logger.log_file is None, "Log file should be None before first log"

    def test_file_created_on_first_log(self, tmp_path):
        """File should be created when first message is logged."""
        log_dir = tmp_path / "logs"

        logger = PipelineLogger(
            scan_id="test-book",
            stage="test-stage",
            log_dir=log_dir
        )

        # Log a message
        logger.info("First message")

        # Now directory and file should exist
        assert log_dir.exists(), "Log directory should be created on first log"
        assert logger.log_file is not None
        assert logger.log_file.exists(), "Log file should exist after logging"

    def test_close_without_logging_creates_nothing(self, tmp_path):
        """Closing an unused logger should not create files."""
        log_dir = tmp_path / "logs"

        logger = PipelineLogger(
            scan_id="test-book",
            stage="test-stage",
            log_dir=log_dir
        )

        logger.close()

        assert not log_dir.exists(), "Close should not create directories"


class TestPipelineLoggerSingleFile:
    """Test single append-only file behavior."""

    def test_filename_has_no_timestamp(self, tmp_path):
        """Log filename should be stage.jsonl, not stage_timestamp.jsonl."""
        log_dir = tmp_path / "logs"

        logger = PipelineLogger(
            scan_id="test-book",
            stage="my-stage",
            log_dir=log_dir
        )

        logger.info("test")

        assert logger.log_file.name == "my-stage.jsonl"

    def test_multiple_loggers_append_to_same_file(self, tmp_path):
        """Multiple logger instances for same stage should append to same file."""
        log_dir = tmp_path / "logs"

        # First logger
        logger1 = PipelineLogger(
            scan_id="test-book",
            stage="shared-stage",
            log_dir=log_dir
        )
        logger1.info("message from logger 1")
        logger1.close()

        # Second logger (simulating a new run)
        logger2 = PipelineLogger(
            scan_id="test-book",
            stage="shared-stage",
            log_dir=log_dir
        )
        logger2.info("message from logger 2")
        logger2.close()

        # Should only have one file
        log_files = list(log_dir.glob("*.jsonl"))
        assert len(log_files) == 1, f"Should have 1 file, got: {[f.name for f in log_files]}"

        # Should have both messages
        with open(log_files[0]) as f:
            lines = f.readlines()

        assert len(lines) == 2, "Should have 2 log entries"
        assert "message from logger 1" in lines[0]
        assert "message from logger 2" in lines[1]


class TestPipelineLoggerJsonFormat:
    """Test JSON log formatting."""

    def test_log_entry_has_required_fields(self, tmp_path):
        """Each log entry should have timestamp, level, message, scan_id, stage."""
        log_dir = tmp_path / "logs"

        logger = PipelineLogger(
            scan_id="test-book",
            stage="test-stage",
            log_dir=log_dir
        )

        logger.info("test message")
        logger.close()

        with open(logger.log_file) as f:
            entry = json.loads(f.readline())

        assert "timestamp" in entry
        assert entry["level"] == "INFO"
        assert entry["message"] == "test message"
        assert entry["scan_id"] == "test-book"
        assert entry["stage"] == "test-stage"

    def test_custom_fields_in_log_entry(self, tmp_path):
        """Custom fields should be included in log entry."""
        log_dir = tmp_path / "logs"

        logger = PipelineLogger(
            scan_id="test-book",
            stage="test-stage",
            log_dir=log_dir
        )

        logger.info("processing page", page=5, cost_usd=0.01)
        logger.close()

        with open(logger.log_file) as f:
            entry = json.loads(f.readline())

        assert entry["page"] == 5
        assert entry["cost_usd"] == 0.01


class TestPipelineLoggerLevels:
    """Test different log levels."""

    def test_all_log_levels(self, tmp_path):
        """All log levels should work and be recorded correctly."""
        log_dir = tmp_path / "logs"

        logger = PipelineLogger(
            scan_id="test-book",
            stage="test-stage",
            log_dir=log_dir,
            level="DEBUG"  # Enable all levels
        )

        logger.debug("debug msg")
        logger.info("info msg")
        logger.warning("warning msg")
        logger.error("error msg")
        logger.close()

        with open(logger.log_file) as f:
            lines = f.readlines()

        entries = [json.loads(line) for line in lines]
        levels = [e["level"] for e in entries]

        assert levels == ["DEBUG", "INFO", "WARNING", "ERROR"]

    def test_level_filtering(self, tmp_path):
        """Log level should filter out lower-priority messages."""
        log_dir = tmp_path / "logs"

        logger = PipelineLogger(
            scan_id="test-book",
            stage="test-stage",
            log_dir=log_dir,
            level="WARNING"  # Only WARNING and above
        )

        logger.debug("should not appear")
        logger.info("should not appear")
        logger.warning("should appear")
        logger.error("should appear")
        logger.close()

        with open(logger.log_file) as f:
            lines = f.readlines()

        assert len(lines) == 2
        entries = [json.loads(line) for line in lines]
        assert entries[0]["level"] == "WARNING"
        assert entries[1]["level"] == "ERROR"


class TestCreateLoggerHelper:
    """Test the create_logger factory function."""

    def test_create_logger_returns_pipeline_logger(self, tmp_path):
        """create_logger should return a PipelineLogger instance."""
        log_dir = tmp_path / "logs"

        logger = create_logger(
            scan_id="test-book",
            stage="test-stage",
            log_dir=log_dir
        )

        assert isinstance(logger, PipelineLogger)
