"""
Tests for infra/pipeline/storage/stage_storage.py

Key behaviors to verify:
1. Lazy directory creation - no dirs until write
2. save_file/load_file operations
3. list_files/list_pages operations
4. Lazy logger creation
5. Lazy metrics_manager creation
"""

import json
import pytest
from pathlib import Path


class TestStageStorageLazyInit:
    """Test that StageStorage initializes lazily."""

    def test_no_directory_created_on_init(self, book_storage):
        """StageStorage should not create output_dir on instantiation."""
        stage = book_storage.stage("lazy-test-stage")

        assert not stage.output_dir.exists(), "output_dir should not exist on init"

    def test_no_log_file_created_on_init(self, book_storage):
        """StageStorage should not create log file on init."""
        stage = book_storage.stage("lazy-test-stage")
        log_file = stage.output_dir / "log.jsonl"

        assert not log_file.exists(), "log file should not exist on init"

    def test_directory_created_on_save(self, book_storage):
        """Directory should be created when saving a file."""
        stage = book_storage.stage("lazy-test-stage")

        stage.save_file("test.json", {"key": "value"})

        assert stage.output_dir.exists(), "output_dir should exist after save"

    def test_logger_is_lazy(self, book_storage):
        """Logger should only be created when accessed."""
        stage = book_storage.stage("logger-test-stage")

        # _logger should be None initially
        assert stage._logger is None

        # Access logger
        logger = stage.logger()

        # Now _logger should exist
        assert stage._logger is not None
        assert logger is stage._logger

    def test_logger_writes_to_stage_dir(self, book_storage):
        """Logger should write log.jsonl inside stage directory."""
        stage = book_storage.stage("log-location-test")

        logger = stage.logger()
        logger.info("test message")

        log_file = stage.output_dir / "log.jsonl"
        assert log_file.exists(), "log.jsonl should be in stage output_dir"

    def test_metrics_manager_is_lazy(self, book_storage):
        """MetricsManager should only be created when accessed."""
        stage = book_storage.stage("metrics-test-stage")

        # _metrics_manager should be None initially
        assert stage._metrics_manager is None

        # Access metrics_manager
        mm = stage.metrics_manager

        # Now should exist
        assert stage._metrics_manager is not None
        assert mm is stage._metrics_manager


class TestStageStorageSaveLoad:
    """Test save and load operations."""

    def test_save_and_load_file(self, book_storage):
        """Should be able to save and load JSON files."""
        stage = book_storage.stage("save-test")
        data = {"foo": "bar", "count": 42}

        stage.save_file("test.json", data)
        loaded = stage.load_file("test.json")

        assert loaded == data

    def test_save_creates_parent_directories(self, book_storage):
        """Saving to a subdir should create intermediate directories."""
        stage = book_storage.stage("subdir-test")

        stage.save_file("deep/nested/file.json", {"nested": True})

        assert (stage.output_dir / "deep" / "nested" / "file.json").exists()

    def test_save_and_load_page(self, book_storage):
        """save_page/load_page should use page_NNNN.json format."""
        stage = book_storage.stage("page-test")
        data = {"text": "page content", "page": 5}

        stage.save_page(5, data)
        loaded = stage.load_page(5)

        assert loaded == data
        assert (stage.output_dir / "page_0005.json").exists()

    def test_save_page_with_subdir(self, book_storage):
        """save_page with subdir should create nested structure."""
        stage = book_storage.stage("subdir-page-test")

        stage.save_page(3, {"data": "test"}, subdir="olm")

        assert (stage.output_dir / "olm" / "page_0003.json").exists()

    def test_load_nonexistent_file_raises(self, book_storage):
        """Loading a nonexistent file should raise FileNotFoundError."""
        stage = book_storage.stage("missing-test")

        with pytest.raises(FileNotFoundError):
            stage.load_file("nonexistent.json")


class TestStageStorageListFiles:
    """Test file listing operations."""

    def test_list_files_empty_stage(self, book_storage):
        """list_files on non-existent stage should return empty list."""
        stage = book_storage.stage("empty-stage")

        result = stage.list_files("*.json")

        assert result == []

    def test_list_files_with_pattern(self, book_storage):
        """list_files should return matching files."""
        stage = book_storage.stage("list-test")

        # Create some files
        stage.save_file("page_0001.json", {"n": 1})
        stage.save_file("page_0002.json", {"n": 2})
        stage.save_file("other.json", {"n": 0})

        result = stage.list_files("page_*.json")

        assert len(result) == 2
        assert all("page_" in f.name for f in result)

    def test_list_pages_returns_integers(self, book_storage):
        """list_pages should return page numbers as integers."""
        stage = book_storage.stage("list-pages-test")

        stage.save_page(1, {"n": 1})
        stage.save_page(5, {"n": 5})
        stage.save_page(10, {"n": 10})

        pages = stage.list_pages()

        assert pages == [1, 5, 10]

    def test_list_pages_with_subdir(self, book_storage):
        """list_pages should work with subdirectories."""
        stage = book_storage.stage("list-subdir-test")

        stage.save_page(1, {"n": 1}, subdir="ocr")
        stage.save_page(2, {"n": 2}, subdir="ocr")
        stage.save_page(1, {"n": 1}, subdir="other")

        ocr_pages = stage.list_pages(subdir="ocr")
        other_pages = stage.list_pages(subdir="other")

        assert ocr_pages == [1, 2]
        assert other_pages == [1]


class TestStageStorageClean:
    """Test stage cleaning operations."""

    def test_clean_removes_stage_directory(self, book_storage):
        """clean() should remove the entire stage directory."""
        stage = book_storage.stage("clean-test")

        # Create some content
        stage.save_file("test.json", {"data": True})
        assert stage.output_dir.exists()

        # Clean
        stage.clean()

        assert not stage.output_dir.exists()

    def test_clean_on_nonexistent_stage_is_safe(self, book_storage):
        """clean() on non-existent stage should not raise."""
        stage = book_storage.stage("never-created")

        # Should not raise
        stage.clean()


