"""
Tests for BookStorage class

Uses real filesystem operations (no mocks) with pytest tmp_path fixtures.
All tests are idempotent and clean up automatically.
"""

import json
import pytest
from pathlib import Path

from infra.storage.book_storage import BookStorage


# ===== Fixtures =====

@pytest.fixture
def book_dir(tmp_path):
    """Create a minimal book directory structure"""
    book = tmp_path / "test-book"
    book.mkdir()

    # Create metadata
    metadata = {
        "title": "Test Book",
        "author": "Test Author",
        "year": 2024,
        "type": "autobiography"
    }
    with open(book / "metadata.json", 'w') as f:
        json.dump(metadata, f, indent=2)

    return book


@pytest.fixture
def book_with_source(book_dir):
    """Book with source pages"""
    source_dir = book_dir / "source"
    source_dir.mkdir()

    # Create 3 source pages
    for i in range(1, 4):
        page_file = source_dir / f"page_{i:04d}.png"
        page_file.write_text(f"fake png data for page {i}")

    return book_dir


@pytest.fixture
def book_with_ocr(book_with_source):
    """Book with OCR outputs (10 pages for metadata stage validation)"""
    ocr_dir = book_with_source / "ocr"
    ocr_dir.mkdir()

    # Create 10 OCR outputs (metadata stage needs at least 10)
    for i in range(1, 11):
        ocr_data = {
            "page_number": i,
            "blocks": [
                {
                    "block_num": 1,
                    "paragraphs": [
                        {"par_num": 1, "text": f"Test text from page {i}"}
                    ]
                }
            ]
        }
        ocr_file = ocr_dir / f"page_{i:04d}.json"
        with open(ocr_file, 'w') as f:
            json.dump(ocr_data, f, indent=2)

    return book_with_source


@pytest.fixture
def book_with_correction(book_with_ocr):
    """Book with correction outputs"""
    corrected_dir = book_with_ocr / "corrected"
    corrected_dir.mkdir()

    # Create 10 correction outputs (match OCR page count)
    for i in range(1, 11):
        correction_data = {
            "page_number": i,
            "blocks": [
                {
                    "block_num": 1,
                    "paragraphs": [
                        {"par_num": 1, "text": None, "notes": "No OCR errors detected", "confidence": 1.0}
                    ]
                }
            ],
            "model_used": "test-model",
            "processing_cost": 0.01,
            "timestamp": "2024-01-01T00:00:00",
            "total_blocks": 1,
            "total_corrections": 0,
            "avg_confidence": 1.0
        }
        correction_file = corrected_dir / f"page_{i:04d}.json"
        with open(correction_file, 'w') as f:
            json.dump(correction_data, f, indent=2)

    return book_with_ocr


@pytest.fixture
def book_with_labels(book_with_correction):
    """Book with label outputs"""
    labels_dir = book_with_correction / "labels"
    labels_dir.mkdir()

    # Create 10 label outputs (match OCR/correction page count)
    for i in range(1, 11):
        label_data = {
            "page_number": i,
            "regions": {"type": "body"}
        }
        label_file = labels_dir / f"page_{i:04d}.json"
        with open(label_file, 'w') as f:
            json.dump(label_data, f, indent=2)

    return book_with_correction


# ===== Basic Initialization =====

def test_book_storage_init(tmp_path):
    """Test BookStorage initialization"""
    book_dir = tmp_path / "test-book"
    book_dir.mkdir()

    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    assert storage.scan_id == "test-book"
    assert storage.storage_root == tmp_path
    assert storage.book_dir == book_dir
    assert storage.exists is True


def test_book_storage_nonexistent_book(tmp_path):
    """Test BookStorage with nonexistent book (should not raise, just exists=False)"""
    storage = BookStorage(scan_id="nonexistent", storage_root=tmp_path)

    assert storage.exists is False
    assert storage.book_dir == tmp_path / "nonexistent"


def test_book_storage_default_root(tmp_path, monkeypatch):
    """Test BookStorage uses default storage root"""
    # Temporarily change HOME to tmp_path
    monkeypatch.setenv("HOME", str(tmp_path))

    storage = BookStorage(scan_id="test-book")

    expected_root = tmp_path / "Documents" / "book_scans"
    assert storage.storage_root == expected_root


# ===== Core Properties =====

def test_book_storage_core_paths(book_dir, tmp_path):
    """Test core path properties"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    assert storage.metadata_file == book_dir / "metadata.json"
    # Generic stage access
    assert storage.stage('ocr').output_dir == book_dir / "ocr"
    assert storage.stage('corrected').output_dir == book_dir / "corrected"
    assert storage.stage('detect-chapters').output_dir == book_dir / "detect-chapters"


# ===== Generic Stage Storage =====

def test_generic_stage_storage(book_dir, tmp_path):
    """Test generic stage storage works for any stage name"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Test various stage names
    ocr = storage.stage('ocr')
    assert ocr.name == "ocr"
    assert ocr.output_dir == book_dir / "ocr"
    assert ocr.output_page(5) == book_dir / "ocr" / "page_0005.json"

    corrected = storage.stage('corrected')
    assert corrected.name == "corrected"
    assert corrected.output_dir == book_dir / "corrected"
    assert corrected.output_page(5) == book_dir / "corrected" / "page_0005.json"

    # Test arbitrary stage names (new stages)
    detect_chapters = storage.stage('detect-chapters')
    assert detect_chapters.name == "detect-chapters"
    assert detect_chapters.output_dir == book_dir / "detect-chapters"
    assert detect_chapters.output_page(1) == book_dir / "detect-chapters" / "page_0001.json"

    extract_quotes = storage.stage('extract-quotes')
    assert extract_quotes.name == "extract-quotes"
    assert extract_quotes.output_dir == book_dir / "extract-quotes"


def test_stage_storage_caching(book_dir, tmp_path):
    """Test that stage storage instances are cached"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Get same stage twice
    ocr1 = storage.stage('ocr')
    ocr2 = storage.stage('ocr')

    # Should be same instance
    assert ocr1 is ocr2


# ===== Directory Management =====

def test_ensure_directories_basic(book_dir, tmp_path):
    """Test ensure_directories creates required directories"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Initially don't exist
    assert not storage.stage('corrected').output_dir.exists()

    # Ensure directories
    dirs = storage.stage('corrected').ensure_directories()

    # Now they exist
    assert storage.stage('corrected').output_dir.exists()

    # Returns correct paths
    assert dirs['output'] == storage.stage('corrected').output_dir


def test_ensure_directories_idempotent(book_dir, tmp_path):
    """Test ensure_directories is idempotent (can be called multiple times)"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Call twice
    dirs1 = storage.stage('corrected').ensure_directories()
    dirs2 = storage.stage('corrected').ensure_directories()

    # Both succeed and return same paths
    assert dirs1 == dirs2
    assert storage.stage('corrected').output_dir.exists()


def test_ensure_directories_ocr_creates_images_dir(book_dir, tmp_path):
    """Test OCR stage ensure_directories creates images/ directory"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # OCR stage creates its output dir (generic behavior)
    dirs = storage.stage('ocr').ensure_directories()
    assert storage.stage('ocr').output_dir.exists()
    assert dirs['output'] == storage.stage('ocr').output_dir

    # Images directory is book-level, not managed by StageStorage
    # (Pipeline code creates it as needed)


# ===== Metadata Operations =====

def test_load_metadata(book_dir, tmp_path):
    """Test load_metadata"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    metadata = storage.load_metadata()

    assert metadata['title'] == "Test Book"
    assert metadata['author'] == "Test Author"
    assert metadata['year'] == 2024


def test_load_metadata_missing_file(tmp_path):
    """Test load_metadata raises FileNotFoundError if metadata missing"""
    book_dir = tmp_path / "test-book"
    book_dir.mkdir()

    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    with pytest.raises(FileNotFoundError, match="Metadata file not found"):
        storage.load_metadata()


def test_save_metadata(book_dir, tmp_path):
    """Test save_metadata (atomic write)"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    new_metadata = {
        "title": "New Title",
        "author": "New Author",
        "pages": 100
    }

    storage.save_metadata(new_metadata)

    # Verify saved
    loaded = storage.load_metadata()
    assert loaded == new_metadata


def test_update_metadata(book_dir, tmp_path):
    """Test update_metadata (partial update)"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Original metadata has title, author, year, type
    storage.update_metadata({
        'correction_complete': True,
        'correction_cost': 5.25,
        'year': 2025  # Update existing field
    })

    metadata = storage.load_metadata()

    # Original fields preserved
    assert metadata['title'] == "Test Book"
    assert metadata['author'] == "Test Author"
    assert metadata['type'] == "autobiography"

    # New fields added
    assert metadata['correction_complete'] is True
    assert metadata['correction_cost'] == 5.25

    # Existing field updated
    assert metadata['year'] == 2025


def test_update_metadata_clear_fields(book_dir, tmp_path):
    """Test update_metadata can clear fields by setting them to None"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Add a field then clear it
    storage.update_metadata({'temp_field': 'value'})
    metadata = storage.load_metadata()
    assert metadata['temp_field'] == 'value'

    # Clear it (update will set to None, which stays in JSON)
    storage.update_metadata({'temp_field': None})
    metadata = storage.load_metadata()
    assert metadata['temp_field'] is None


def test_metadata_operations_thread_safe(book_dir, tmp_path):
    """Test metadata operations use locks (basic smoke test)"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Multiple updates should succeed without corruption
    storage.update_metadata({'field1': 1})
    storage.update_metadata({'field2': 2})
    storage.update_metadata({'field3': 3})

    metadata = storage.load_metadata()
    assert metadata['field1'] == 1
    assert metadata['field2'] == 2
    assert metadata['field3'] == 3


def test_concurrent_metadata_updates(book_dir, tmp_path):
    """Test concurrent metadata updates maintain atomicity (no lost updates)"""
    import threading

    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Initialize counter field
    storage.update_metadata({'counter': 0})

    # Number of threads and increments per thread
    num_threads = 10
    increments_per_thread = 50

    def increment_counter():
        """Each thread increments counter multiple times"""
        for _ in range(increments_per_thread):
            # Read current value, increment, write back
            # If not atomic, updates will be lost
            metadata = storage.load_metadata()
            current = metadata['counter']
            storage.update_metadata({'counter': current + 1})

    # Spawn threads
    threads = []
    for _ in range(num_threads):
        t = threading.Thread(target=increment_counter)
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Verify all updates were preserved
    final_metadata = storage.load_metadata()
    expected = num_threads * increments_per_thread

    # Without proper locking, we'd lose updates (counter < expected)
    # With proper locking, all updates are preserved (counter == expected)
    assert final_metadata['counter'] == expected, \
        f"Lost updates detected: expected {expected}, got {final_metadata['counter']}"


# ===== List Operations =====

def test_list_output_pages_empty(book_dir, tmp_path):
    """Test list_output_pages with no pages"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    pages = storage.stage('ocr').list_output_pages()

    assert pages == []


def test_list_output_pages_with_pages(book_with_ocr, tmp_path):
    """Test list_output_pages returns sorted pages"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    pages = storage.stage('ocr').list_output_pages()

    assert len(pages) == 10
    assert pages[0].name == "page_0001.json"
    assert pages[1].name == "page_0002.json"
    assert pages[9].name == "page_0010.json"


def test_list_source_pages(book_with_source, tmp_path):
    """Test list_output_pages for source PNG files"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    pages = storage.stage('source').list_output_pages(extension='png')

    assert len(pages) == 3
    assert pages[0].name == "page_0001.png"
    assert pages[2].name == "page_0003.png"


def test_list_output_pages_different_extensions(book_dir, tmp_path):
    """Test list_output_pages with custom extension"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Create output directory with mixed files
    output_dir = storage.stage('ocr').output_dir
    output_dir.mkdir()
    (output_dir / "page_0001.json").write_text("{}")
    (output_dir / "page_0002.json").write_text("{}")
    (output_dir / "page_0001.txt").write_text("text")

    # List only JSON files
    json_pages = storage.stage('ocr').list_output_pages(extension="json")
    assert len(json_pages) == 2

    # List only TXT files
    txt_pages = storage.stage('ocr').list_output_pages(extension="txt")
    assert len(txt_pages) == 1


# ===== Validation =====

def test_validate_book_complete(book_with_source, tmp_path):
    """Test validate_book with complete book structure"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    result = storage.validate_book()

    assert result['book_dir_exists'] is True
    assert result['metadata_exists'] is True
    assert result['source_dir_exists'] is True
    assert result['has_source_pages'] is True


def test_validate_book_incomplete(book_dir, tmp_path):
    """Test validate_book with incomplete book structure"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    result = storage.validate_book()

    assert result['book_dir_exists'] is True
    assert result['metadata_exists'] is True
    assert result['source_dir_exists'] is False  # No source dir created
    assert result['has_source_pages'] is False


def test_source_validate_inputs(book_dir, tmp_path):
    """Test source stage validation (basic book check)"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Should succeed - book exists
    assert storage.stage('source').validate_inputs() is True


# Stage-specific validation tests removed - this logic now lives in pipeline code
# Generic StageStorage only provides basic book directory validation

# ===== Integration Tests =====

def test_full_pipeline_flow(tmp_path):
    """Test complete pipeline flow through all stages"""
    # Setup book
    book_dir = tmp_path / "test-book"
    book_dir.mkdir()

    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Create metadata
    storage.save_metadata({
        "title": "Integration Test Book",
        "author": "Test Author"
    })

    # Stage 1: Source
    storage.stage('source').ensure_directories()
    for i in range(1, 11):
        storage.stage('source').output_page(i, extension='png').write_text(f"page {i}")

    assert len(storage.stage('source').list_output_pages(extension='png')) == 10

    # Stage 2: OCR
    storage.stage('ocr').validate_inputs()
    storage.stage('ocr').ensure_directories()
    for i in range(1, 11):
        storage.stage('ocr').output_page(i).write_text('{"page_number": ' + str(i) + '}')

    assert len(storage.stage('ocr').list_output_pages()) == 10

    # Stage 3: Metadata extraction
    storage.stage('metadata').validate_inputs()
    # (metadata already exists)

    # Stage 4: Correction
    storage.stage('corrected').validate_inputs()
    storage.stage('corrected').ensure_directories()
    for i in range(1, 11):
        storage.stage('corrected').output_page(i).write_text('{"corrected": true}')

    assert len(storage.stage('corrected').list_output_pages()) == 10

    # Stage 5: Label
    storage.stage('labels').validate_inputs()
    storage.stage('labels').ensure_directories()
    for i in range(1, 11):
        storage.stage('labels').output_page(i).write_text('{"labeled": true}')

    assert len(storage.stage('labels').list_output_pages()) == 10

    # Stage 6: Merge
    storage.stage('processed').validate_inputs()
    storage.stage('processed').ensure_directories()
    for i in range(1, 11):
        storage.stage('processed').output_page(i).write_text('{"merged": true}')

    assert len(storage.stage('processed').list_output_pages()) == 10

    # Stage 7: Structure
    storage.stage('chapters').validate_inputs()
    storage.stage('chapters').ensure_directories()

    # Final validation
    validation = storage.validate_book()
    assert all(validation.values())


def test_concurrent_stage_operations(book_with_source, tmp_path):
    """Test multiple stage storages can operate concurrently"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Ensure directories for multiple stages concurrently
    ocr_dirs = storage.stage('ocr').ensure_directories()
    correction_dirs = storage.stage('corrected').ensure_directories()
    label_dirs = storage.stage('labels').ensure_directories()

    # All should succeed
    assert ocr_dirs['output'].exists()
    assert correction_dirs['output'].exists()
    assert label_dirs['output'].exists()

    # Each stage has its own output directory
    assert ocr_dirs['output'] != correction_dirs['output']
    assert correction_dirs['output'] != label_dirs['output']


# ===== Checkpoint Integration Tests =====

def test_stage_storage_checkpoint_property(book_dir, tmp_path):
    """Test stage storage checkpoint property is lazily initialized"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)

    # Access checkpoint (lazy initialization)
    checkpoint = storage.stage('corrected').checkpoint

    # Verify checkpoint is initialized correctly
    assert checkpoint.scan_id == "test-book"
    assert checkpoint.stage == "corrected"  # Stage name matches what we passed
    assert checkpoint.output_dir == "corrected"
    # Checkpoint is in stage directory now
    assert checkpoint.checkpoint_file == storage.stage('corrected').output_dir / ".checkpoint"

    # Accessing again returns same instance
    checkpoint2 = storage.stage('corrected').checkpoint
    assert checkpoint is checkpoint2


def test_stage_view_save_page_basic(book_dir, tmp_path):
    """Test save_page creates output file and updates checkpoint"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)
    storage.stage('corrected').ensure_directories()

    # Save a single page
    page_data = {
        "page_number": 1,
        "blocks": [{"block_num": 1, "paragraphs": []}],
        "model_used": "test-model",
        "processing_cost": 0.01,
        "timestamp": "2024-01-01T00:00:00",
        "total_blocks": 1,
        "total_corrections": 0,
        "avg_confidence": 1.0
    }

    storage.stage('corrected').save_page(
        page_num=1,
        data=page_data,
        cost_usd=0.02,
        processing_time=1.5
    )

    # Verify file was written
    output_file = storage.stage('corrected').output_page(1)
    assert output_file.exists()

    with open(output_file, 'r') as f:
        saved_data = json.load(f)
    assert saved_data == page_data

    # Verify checkpoint was updated
    checkpoint = storage.stage('corrected').checkpoint
    status = checkpoint.get_status()
    assert 1 in status['completed_pages']
    assert status['metadata']['total_cost_usd'] == 0.02


def test_stage_view_save_page_atomic(book_dir, tmp_path):
    """Test save_page is atomic (uses temp file)"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)
    storage.stage('corrected').ensure_directories()

    page_data = {
        "page_number": 1,
        "blocks": []
    }

    storage.stage('corrected').save_page(
        page_num=1,
        data=page_data,
        cost_usd=0.01
    )

    # Verify no temp files left behind
    output_dir = storage.stage('corrected').output_dir
    temp_files = list(output_dir.glob("*.tmp"))
    assert len(temp_files) == 0

    # Verify actual file exists
    assert storage.stage('corrected').output_page(1).exists()


def test_stage_view_save_page_cost_accumulation(book_dir, tmp_path):
    """Test save_page accumulates costs in checkpoint"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)
    storage.stage('corrected').ensure_directories()

    # Save 3 pages with different costs
    for i in range(1, 4):
        storage.stage('corrected').save_page(
            page_num=i,
            data={"page_number": i, "blocks": []},
            cost_usd=0.01 * i,  # 0.01, 0.02, 0.03
            processing_time=1.0
        )

    # Verify checkpoint accumulated costs
    checkpoint = storage.stage('corrected').checkpoint
    status = checkpoint.get_status()

    assert len(status['completed_pages']) == 3
    assert status['completed_pages'] == [1, 2, 3]
    assert status['metadata']['total_cost_usd'] == 0.06  # 0.01 + 0.02 + 0.03


def test_stage_view_save_page_thread_safety(book_dir, tmp_path):
    """Test save_page is thread-safe for concurrent writes"""
    import threading

    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)
    storage.stage('corrected').ensure_directories()

    # Initialize checkpoint before spawning threads to avoid race conditions
    # during lazy initialization (multiple threads trying to create checkpoint)
    _ = storage.stage('corrected').checkpoint

    num_threads = 10
    pages_per_thread = 5

    def save_pages(thread_id):
        """Each thread saves multiple pages"""
        start_page = thread_id * pages_per_thread + 1
        for i in range(start_page, start_page + pages_per_thread):
            storage.stage('corrected').save_page(
                page_num=i,
                data={"page_number": i, "blocks": [], "thread": thread_id},
                cost_usd=0.01,
                processing_time=0.5
            )

    # Spawn threads
    threads = []
    for tid in range(num_threads):
        t = threading.Thread(target=save_pages, args=(tid,))
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Verify all pages were saved
    expected_pages = num_threads * pages_per_thread
    saved_pages = storage.stage('corrected').list_output_pages()
    assert len(saved_pages) == expected_pages

    # Verify checkpoint tracked all pages
    checkpoint = storage.stage('corrected').checkpoint
    status = checkpoint.get_status()
    assert len(status['completed_pages']) == expected_pages
    # Use approximate comparison for floating point cost
    assert abs(status['metadata']['total_cost_usd'] - expected_pages * 0.01) < 0.001


def test_stage_view_save_page_large_batch(book_dir, tmp_path):
    """Test save_page handles large batch (500 pages) correctly"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)
    storage.stage('corrected').ensure_directories()

    num_pages = 500
    cost_per_page = 0.023
    time_per_page = 2.5

    # Initialize checkpoint with total_pages (simulates what stages do)
    checkpoint = storage.stage('corrected').checkpoint
    checkpoint.get_remaining_pages(total_pages=num_pages, resume=False)

    # Save 500 pages
    for page_num in range(1, num_pages + 1):
        storage.stage('corrected').save_page(
            page_num=page_num,
            data={
                "page_number": page_num,
                "blocks": [{"block_num": 1, "paragraphs": []}],
                "model_used": "test-model",
                "processing_cost": cost_per_page,
                "timestamp": "2024-01-01T00:00:00",
                "total_blocks": 1,
                "total_corrections": 0,
                "avg_confidence": 1.0
            },
            cost_usd=cost_per_page,
            processing_time=time_per_page
        )

    # Verify all pages were saved to filesystem
    saved_pages = storage.stage('corrected').list_output_pages()
    assert len(saved_pages) == num_pages
    assert saved_pages[0].name == "page_0001.json"
    assert saved_pages[-1].name == "page_0500.json"

    # Verify checkpoint tracked all pages
    status = checkpoint.get_status()

    assert len(status['completed_pages']) == num_pages
    assert status['completed_pages'] == list(range(1, num_pages + 1))

    # Verify cost accumulation
    expected_total_cost = num_pages * cost_per_page
    actual_total_cost = status['metadata']['total_cost_usd']
    assert abs(actual_total_cost - expected_total_cost) < 0.01  # Allow for floating point precision

    # Verify progress tracking
    assert status['progress']['completed'] == num_pages
    assert status['progress']['percent'] == 100.0
    assert status['total_pages'] == num_pages

    # Verify checkpoint file was written
    assert checkpoint.checkpoint_file.exists()

    # Verify checkpoint can be reloaded
    from infra.storage.checkpoint import CheckpointManager
    reloaded_checkpoint = CheckpointManager(
        scan_id="test-book",
        stage="correction",
        storage_root=tmp_path,
        output_dir="corrected"
    )
    reloaded_status = reloaded_checkpoint.get_status()
    assert reloaded_status['completed_pages'] == list(range(1, num_pages + 1))
    assert abs(reloaded_status['metadata']['total_cost_usd'] - expected_total_cost) < 0.01


def test_stage_view_checkpoint_resume_workflow(book_dir, tmp_path):
    """Test checkpoint enables resume workflow through stage view"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)
    storage.stage('corrected').ensure_directories()

    total_pages = 100

    # First run: Save first 50 pages
    for i in range(1, 51):
        storage.stage('corrected').save_page(
            page_num=i,
            data={"page_number": i, "blocks": []},
            cost_usd=0.01
        )

    # Get remaining pages (should return pages 51-100)
    checkpoint = storage.stage('corrected').checkpoint
    remaining = checkpoint.get_remaining_pages(total_pages=total_pages, resume=True)

    assert len(remaining) == 50
    assert remaining[0] == 51
    assert remaining[-1] == 100

    # Second run: Save remaining pages
    for page_num in remaining:
        storage.stage('corrected').save_page(
            page_num=page_num,
            data={"page_number": page_num, "blocks": []},
            cost_usd=0.01
        )

    # Verify all pages complete
    status = checkpoint.get_status()
    assert len(status['completed_pages']) == total_pages
    assert status['progress']['percent'] == 100.0


def test_stage_view_checkpoint_per_stage_isolation(book_dir, tmp_path):
    """Test each stage view has its own isolated checkpoint"""
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)
    storage.stage('corrected').ensure_directories()
    storage.stage('labels').ensure_directories()

    # Save pages in correction stage
    for i in range(1, 6):
        storage.stage('corrected').save_page(
            page_num=i,
            data={"page_number": i, "blocks": []},
            cost_usd=0.01
        )

    # Save pages in label stage (labels have different schema)
    for i in range(1, 4):
        storage.stage('labels').save_page(
            page_num=i,
            data={"page_number": i, "regions": {}},
            cost_usd=0.02
        )

    # Verify correction checkpoint
    correction_status = storage.stage('corrected').checkpoint.get_status()
    assert len(correction_status['completed_pages']) == 5
    assert correction_status['metadata']['total_cost_usd'] == 0.05

    # Verify label checkpoint (separate)
    label_status = storage.stage('labels').checkpoint.get_status()
    assert len(label_status['completed_pages']) == 3
    assert label_status['metadata']['total_cost_usd'] == 0.06

    # Checkpoints are independent
    assert correction_status != label_status
