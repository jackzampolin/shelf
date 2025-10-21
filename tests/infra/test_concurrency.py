"""
Concurrency tests for storage layer.

Tests thread safety of LibraryStorage, BookStorage, and StageStorage
under concurrent access patterns.
"""

import pytest
import threading
import json
import time
from pathlib import Path
from infra.storage.library_storage import LibraryStorage
from infra.storage.book_storage import BookStorage


class TestLibraryStorageConcurrency:
    """Test LibraryStorage thread safety."""

    def test_concurrent_add_book(self, tmp_path):
        """Test concurrent add_book operations don't cause race conditions."""
        library = LibraryStorage(storage_root=tmp_path)
        errors = []

        def add_books(start_idx, count):
            try:
                for i in range(start_idx, start_idx + count):
                    library.add_book(
                        title=f"Book {i}",
                        author=f"Author {i}",
                        scan_id=f"scan-{i}"
                    )
            except Exception as e:
                errors.append(e)

        # Run 5 threads adding 20 books each
        threads = []
        for i in range(5):
            t = threading.Thread(target=add_books, args=(i * 20, 20))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Check no errors occurred
        assert len(errors) == 0, f"Errors during concurrent add_book: {errors}"

        # Verify all 100 books were added
        assert len(library.data["books"]) == 100

        # Verify library stats are correct
        assert library.data["stats"]["total_books"] == 100
        assert library.data["stats"]["total_scans"] == 100

    def test_concurrent_update_scan_metadata(self, tmp_path):
        """Test concurrent update_scan_metadata doesn't lose updates."""
        library = LibraryStorage(storage_root=tmp_path)

        # Add 10 books
        for i in range(10):
            library.add_book(
                title=f"Book {i}",
                author=f"Author {i}",
                scan_id=f"scan-{i}"
            )

        errors = []

        def update_metadata(scan_idx):
            try:
                for _ in range(10):
                    library.update_scan_metadata(
                        f"scan-{scan_idx}",
                        {"cost_usd": scan_idx * 0.1}
                    )
            except Exception as e:
                errors.append(e)

        # Run 10 threads updating different scans
        threads = []
        for i in range(10):
            t = threading.Thread(target=update_metadata, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Check no errors occurred
        assert len(errors) == 0, f"Errors during concurrent updates: {errors}"

        # Verify all costs were set correctly
        for i in range(10):
            scan_info = library.get_scan_info(f"scan-{i}")
            assert scan_info["scan"]["cost_usd"] == i * 0.1

    def test_concurrent_mixed_operations(self, tmp_path):
        """Test mixed concurrent operations (add, update, read)."""
        library = LibraryStorage(storage_root=tmp_path)

        # Pre-populate some books
        for i in range(10):
            library.add_book(
                title=f"Book {i}",
                author=f"Author {i}",
                scan_id=f"scan-{i}"
            )

        errors = []
        read_results = []

        def add_books():
            try:
                for i in range(10, 20):
                    library.add_book(
                        title=f"Book {i}",
                        author=f"Author {i}",
                        scan_id=f"scan-{i}"
                    )
            except Exception as e:
                errors.append(e)

        def update_scans():
            try:
                for i in range(10):
                    library.update_scan_metadata(
                        f"scan-{i}",
                        {"pages": i * 100}
                    )
            except Exception as e:
                errors.append(e)

        def read_scans():
            try:
                for i in range(10):
                    info = library.get_scan_info(f"scan-{i}")
                    if info:
                        read_results.append(info)
            except Exception as e:
                errors.append(e)

        # Run mixed operations concurrently
        threads = [
            threading.Thread(target=add_books),
            threading.Thread(target=update_scans),
            threading.Thread(target=read_scans),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Check no errors occurred
        assert len(errors) == 0, f"Errors during concurrent operations: {errors}"

        # Verify final state
        assert len(library.data["books"]) == 20
        assert len(read_results) > 0  # At least some reads succeeded


class TestStageStorageConcurrency:
    """Test StageStorage thread safety."""

    def test_concurrent_checkpoint_initialization(self, tmp_path):
        """Test checkpoint lazy initialization is thread-safe."""
        scan_id = "test-scan"
        scan_dir = tmp_path / scan_id
        scan_dir.mkdir()

        # Create metadata
        metadata = {
            "title": "Test Book",
            "author": "Test Author",
            "total_pages": 100
        }
        with open(scan_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f)

        storage = BookStorage(scan_id=scan_id, storage_root=tmp_path)
        stage = storage.stage('corrected')

        checkpoint_instances = []
        errors = []

        def get_checkpoint():
            try:
                checkpoint_instances.append(stage.checkpoint)
            except Exception as e:
                errors.append(e)

        # Run 10 threads accessing checkpoint simultaneously
        threads = []
        for _ in range(10):
            t = threading.Thread(target=get_checkpoint)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Check no errors occurred
        assert len(errors) == 0, f"Errors during checkpoint init: {errors}"

        # Verify all threads got the SAME checkpoint instance
        assert len(checkpoint_instances) == 10
        assert len(set(id(cp) for cp in checkpoint_instances)) == 1, \
            "Multiple checkpoint instances created (race condition!)"

    def test_concurrent_save_page(self, tmp_path):
        """Test concurrent save_page operations are thread-safe."""
        scan_id = "test-scan"
        scan_dir = tmp_path / scan_id
        scan_dir.mkdir()

        # Create metadata
        metadata = {
            "title": "Test Book",
            "author": "Test Author",
            "total_pages": 100
        }
        with open(scan_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f)

        storage = BookStorage(scan_id=scan_id, storage_root=tmp_path)
        stage = storage.stage('corrected')

        errors = []

        def save_pages(start_page, count):
            try:
                for i in range(start_page, start_page + count):
                    data = {
                        "page_number": i,
                        "text": f"Page {i} content"
                    }
                    stage.save_page(i, data, cost_usd=0.01)
            except Exception as e:
                errors.append(e)

        # Run 5 threads saving 20 pages each
        threads = []
        for i in range(5):
            t = threading.Thread(target=save_pages, args=(i * 20 + 1, 20))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Check no errors occurred
        assert len(errors) == 0, f"Errors during concurrent save_page: {errors}"

        # Verify all 100 pages were saved
        saved_pages = list(stage.list_output_pages())
        assert len(saved_pages) == 100

        # Verify checkpoint tracked all pages
        checkpoint_status = stage.checkpoint.get_status()
        assert len(checkpoint_status["completed_pages"]) == 100


class TestBookStorageConcurrency:
    """Test BookStorage thread safety."""

    def test_concurrent_metadata_updates(self, tmp_path):
        """Test concurrent metadata updates don't lose data."""
        scan_id = "test-scan"
        scan_dir = tmp_path / scan_id
        scan_dir.mkdir()

        # Create initial metadata
        metadata = {
            "title": "Test Book",
            "author": "Test Author",
            "total_pages": 100
        }
        with open(scan_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f)

        storage = BookStorage(scan_id=scan_id, storage_root=tmp_path)

        errors = []
        update_count = [0]  # Use list for mutability in closure

        def update_metadata(field, value):
            try:
                for _ in range(50):
                    storage.update_metadata({field: value})
                    update_count[0] += 1
            except Exception as e:
                errors.append(e)

        # Run 5 threads updating different fields
        threads = [
            threading.Thread(target=update_metadata, args=("field1", "value1")),
            threading.Thread(target=update_metadata, args=("field2", "value2")),
            threading.Thread(target=update_metadata, args=("field3", "value3")),
            threading.Thread(target=update_metadata, args=("field4", "value4")),
            threading.Thread(target=update_metadata, args=("field5", "value5")),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Check no errors occurred
        assert len(errors) == 0, f"Errors during concurrent updates: {errors}"

        # Verify all updates succeeded
        assert update_count[0] == 250

        # Verify final metadata has all fields
        final_metadata = storage.load_metadata()
        assert final_metadata["field1"] == "value1"
        assert final_metadata["field2"] == "value2"
        assert final_metadata["field3"] == "value3"
        assert final_metadata["field4"] == "value4"
        assert final_metadata["field5"] == "value5"


class TestLockOrdering:
    """Test that lock ordering is followed to prevent deadlocks."""

    def test_library_and_book_storage_no_deadlock(self, tmp_path):
        """Test concurrent access to library and book storage doesn't deadlock."""
        library = LibraryStorage(storage_root=tmp_path)

        # Add a book
        library.add_book(
            title="Test Book",
            author="Test Author",
            scan_id="test-scan"
        )

        # Create book directory and metadata
        scan_dir = tmp_path / "test-scan"
        scan_dir.mkdir(exist_ok=True)
        metadata = {
            "title": "Test Book",
            "author": "Test Author",
            "total_pages": 100
        }
        with open(scan_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f)

        storage = library.get_book_storage("test-scan")

        errors = []

        def update_library_and_book():
            try:
                for i in range(50):
                    library.update_scan_metadata("test-scan", {"cost_usd": i * 0.1})
                    storage.update_metadata({"iteration": i})
            except Exception as e:
                errors.append(e)

        # Run 3 threads doing mixed updates
        threads = []
        for _ in range(3):
            t = threading.Thread(target=update_library_and_book)
            threads.append(t)
            t.start()

        # Set timeout to detect deadlock
        for t in threads:
            t.join(timeout=10.0)
            assert not t.is_alive(), "Thread still running - possible deadlock!"

        # Check no errors occurred
        assert len(errors) == 0, f"Errors during concurrent operations: {errors}"


class TestCheckpointRaceConditions:
    """Test checkpoint manager race conditions."""

    def test_concurrent_checkpoint_updates(self, tmp_path):
        """Test concurrent checkpoint mark_completed calls are safe."""
        scan_id = "test-scan"
        scan_dir = tmp_path / scan_id
        scan_dir.mkdir()

        # Create metadata
        metadata = {
            "title": "Test Book",
            "author": "Test Author",
            "total_pages": 100
        }
        with open(scan_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f)

        storage = BookStorage(scan_id=scan_id, storage_root=tmp_path)
        stage = storage.stage('corrected')
        checkpoint = stage.checkpoint

        errors = []

        def mark_pages_complete(start_page, count):
            try:
                for i in range(start_page, start_page + count):
                    checkpoint.mark_completed(i, cost_usd=0.01)
            except Exception as e:
                errors.append(e)

        # Run 5 threads marking 20 pages each
        threads = []
        for i in range(5):
            t = threading.Thread(target=mark_pages_complete, args=(i * 20 + 1, 20))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Check no errors occurred
        assert len(errors) == 0, f"Errors during concurrent checkpoint updates: {errors}"

        # Verify all 100 pages were marked complete
        status = checkpoint.get_status()
        assert len(status["completed_pages"]) == 100

        # Verify total cost is correct (stored in metadata)
        total_cost = status.get("metadata", {}).get("total_cost_usd", 0.0)
        assert abs(total_cost - 1.0) < 0.01  # 100 pages * $0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
