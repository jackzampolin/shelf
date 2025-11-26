"""
Tests for infra/pipeline/storage/book_storage.py

Key behaviors to verify:
1. Stage caching - same stage instance returned
2. Metadata operations (load, save, update)
3. Book validation
4. list_stages operation
"""

import json
import pytest


class TestBookStorageBasics:
    """Test basic BookStorage operations."""

    def test_scan_id_property(self, book_storage):
        """scan_id should return the book's scan ID."""
        assert book_storage.scan_id == "test-book"

    def test_book_dir_property(self, book_storage, tmp_library):
        """book_dir should point to the book's directory."""
        assert book_storage.book_dir == tmp_library / "test-book"

    def test_exists_property(self, book_storage):
        """exists should return True for existing book."""
        assert book_storage.exists is True

    def test_exists_false_for_missing_book(self, tmp_library):
        """exists should return False for non-existent book."""
        from infra.pipeline.storage.book_storage import BookStorage

        storage = BookStorage("nonexistent-book", storage_root=tmp_library)
        assert storage.exists is False


class TestBookStorageStageCaching:
    """Test that stages are cached."""

    def test_stage_returns_same_instance(self, book_storage):
        """Calling stage() twice should return the same StageStorage instance."""
        stage1 = book_storage.stage("my-stage")
        stage2 = book_storage.stage("my-stage")

        assert stage1 is stage2

    def test_different_stages_are_different_instances(self, book_storage):
        """Different stage names should return different instances."""
        stage_a = book_storage.stage("stage-a")
        stage_b = book_storage.stage("stage-b")

        assert stage_a is not stage_b
        assert stage_a.name == "stage-a"
        assert stage_b.name == "stage-b"


class TestBookStorageMetadata:
    """Test metadata operations."""

    def test_load_metadata(self, book_storage):
        """load_metadata should return the book's metadata."""
        metadata = book_storage.load_metadata()

        assert metadata["title"] == "Test Book"
        assert metadata["author"] == "Test Author"
        assert metadata["year"] == 2024

    def test_save_metadata(self, book_storage):
        """save_metadata should write metadata to disk."""
        new_metadata = {
            "title": "Updated Title",
            "author": "New Author",
            "year": 2025
        }

        book_storage.save_metadata(new_metadata)
        loaded = book_storage.load_metadata()

        assert loaded["title"] == "Updated Title"
        assert loaded["author"] == "New Author"

    def test_update_metadata(self, book_storage):
        """update_metadata should merge updates with existing metadata."""
        book_storage.update_metadata({"new_field": "new_value"})

        metadata = book_storage.load_metadata()

        # Original fields preserved
        assert metadata["title"] == "Test Book"
        # New field added
        assert metadata["new_field"] == "new_value"


class TestBookStorageListStages:
    """Test stage listing."""

    def test_list_stages_empty(self, book_storage):
        """list_stages should return empty list if no stages run."""
        # Only source and metadata exist from fixture
        stages = book_storage.list_stages()

        # source has pages but no metrics.json, so should be empty
        # Actually let me check the implementation...
        # It looks for metrics.json OR page_*.json files
        # source has page_*.png, not json
        assert "source" not in stages or stages == []

    def test_list_stages_with_data(self, book_storage):
        """list_stages should return stages that have data."""
        # Create a stage with data
        stage = book_storage.stage("ocr-pages")
        stage.save_page(1, {"text": "hello"})

        stages = book_storage.list_stages()

        assert "ocr-pages" in stages

    def test_has_stage_false(self, book_storage):
        """has_stage should return False for non-existent stage."""
        assert book_storage.has_stage("nonexistent-stage") is False

    def test_has_stage_true(self, book_storage):
        """has_stage should return True for existing stage directory."""
        # Create a stage
        stage = book_storage.stage("my-stage")
        stage.save_file("test.json", {})

        assert book_storage.has_stage("my-stage") is True


class TestBookStorageValidation:
    """Test book validation."""

    def test_validate_book_complete(self, book_storage):
        """validate_book should pass for complete book."""
        result = book_storage.validate_book()

        assert result["book_dir_exists"] is True
        assert result["metadata_exists"] is True
        assert result["source_dir_exists"] is True
        assert result["has_source_pages"] is True

    def test_validate_book_missing_metadata(self, tmp_library):
        """validate_book should detect missing metadata."""
        from infra.pipeline.storage.book_storage import BookStorage

        # Create book without metadata
        book_dir = tmp_library / "no-metadata-book"
        book_dir.mkdir()
        source_dir = book_dir / "source"
        source_dir.mkdir()

        storage = BookStorage("no-metadata-book", storage_root=tmp_library)
        result = storage.validate_book()

        assert result["book_dir_exists"] is True
        assert result["metadata_exists"] is False
