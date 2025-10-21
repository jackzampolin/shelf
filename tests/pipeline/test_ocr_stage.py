"""Tests for pipeline/ocr (new BaseStage implementation)"""

import json
from pathlib import Path
import pytest

from pipeline.ocr import OCRStage
from pipeline.ocr.schemas import OCRPageOutput
from infra.pipeline.runner import run_stage
from infra.storage.book_storage import BookStorage


# ============================================================================
# Schema Validation Tests (same as before - schema hasn't changed)
# ============================================================================

def test_schema_validation_valid_output():
    """Test that valid OCR output passes schema validation."""
    valid_page = {
        "page_number": 1,
        "page_dimensions": {"width": 1000, "height": 1500},
        "ocr_timestamp": "2025-01-01T00:00:00",
        "blocks": [
            {
                "block_num": 0,
                "bbox": [100, 200, 500, 300],
                "paragraphs": [
                    {
                        "par_num": 0,
                        "bbox": [100, 200, 500, 100],
                        "text": "Test paragraph text",
                        "avg_confidence": 0.95
                    }
                ]
            }
        ],
        "images": []
    }

    # Should not raise
    validated = OCRPageOutput(**valid_page)
    assert validated.page_number == 1
    assert len(validated.blocks) == 1
    assert validated.blocks[0].paragraphs[0].text == "Test paragraph text"


def test_schema_validation_requires_paragraphs():
    """Test that blocks must have at least one paragraph."""
    invalid_page = {
        "page_number": 1,
        "page_dimensions": {"width": 1000, "height": 1500},
        "ocr_timestamp": "2025-01-01T00:00:00",
        "blocks": [
            {
                "block_num": 0,
                "bbox": [100, 200, 500, 300],
                "paragraphs": []  # Empty!
            }
        ],
        "images": []
    }

    try:
        OCRPageOutput(**invalid_page)
        assert False, "Should have raised validation error"
    except Exception as e:
        assert "at least one paragraph" in str(e)


def test_schema_validation_unique_block_nums():
    """Test that block numbers must be unique."""
    invalid_page = {
        "page_number": 1,
        "page_dimensions": {"width": 1000, "height": 1500},
        "ocr_timestamp": "2025-01-01T00:00:00",
        "blocks": [
            {
                "block_num": 0,
                "bbox": [100, 200, 500, 300],
                "paragraphs": [
                    {"par_num": 0, "bbox": [100, 200, 500, 100], "text": "Test", "avg_confidence": 0.9}
                ]
            },
            {
                "block_num": 0,  # Duplicate!
                "bbox": [100, 500, 500, 300],
                "paragraphs": [
                    {"par_num": 0, "bbox": [100, 500, 500, 100], "text": "Test", "avg_confidence": 0.9}
                ]
            }
        ],
        "images": []
    }

    try:
        OCRPageOutput(**invalid_page)
        assert False, "Should have raised validation error"
    except Exception as e:
        assert "unique" in str(e)


def test_schema_validation_bbox_from_list():
    """Test that bbox can be provided as list and is converted."""
    page = {
        "page_number": 1,
        "page_dimensions": {"width": 1000, "height": 1500},
        "ocr_timestamp": "2025-01-01T00:00:00",
        "blocks": [
            {
                "block_num": 0,
                "bbox": [100, 200, 500, 300],  # List format
                "paragraphs": [
                    {
                        "par_num": 0,
                        "bbox": [100, 200, 500, 100],  # List format
                        "text": "Test",
                        "avg_confidence": 0.9
                    }
                ]
            }
        ],
        "images": []
    }

    validated = OCRPageOutput(**page)
    assert validated.blocks[0].bbox.x == 100
    assert validated.blocks[0].bbox.y == 200
    assert validated.blocks[0].bbox.width == 500
    assert validated.blocks[0].bbox.height == 300


def test_schema_helpers():
    """Test helper methods on OCRPageOutput schema."""
    page = OCRPageOutput(**{
        "page_number": 1,
        "page_dimensions": {"width": 1000, "height": 1500},
        "ocr_timestamp": "2025-01-01T00:00:00",
        "blocks": [
            {
                "block_num": 0,
                "bbox": [100, 200, 500, 100],
                "paragraphs": [
                    {"par_num": 0, "bbox": [100, 200, 500, 100], "text": "Single para", "avg_confidence": 0.9}
                ]
            },
            {
                "block_num": 1,
                "bbox": [100, 400, 500, 200],
                "paragraphs": [
                    {"par_num": 0, "bbox": [100, 400, 500, 100], "text": "Para 1", "avg_confidence": 0.9},
                    {"par_num": 1, "bbox": [100, 500, 500, 100], "text": "Para 2", "avg_confidence": 0.9}
                ]
            }
        ],
        "images": [
            {"image_id": 1, "bbox": [200, 700, 300, 200], "image_file": "img_001.png"}
        ]
    })

    # Test get_isolated_blocks (single-paragraph blocks)
    isolated = page.get_isolated_blocks()
    assert len(isolated) == 1
    assert isolated[0].block_num == 0

    # Test get_continuous_blocks (multi-paragraph blocks)
    continuous = page.get_continuous_blocks()
    assert len(continuous) == 1
    assert continuous[0].block_num == 1

    # Test get_all_text
    all_text = page.get_all_text()
    assert "Single para" in all_text
    assert "Para 1" in all_text
    assert "Para 2" in all_text

    # Test find_nearby_blocks
    nearby = page.find_nearby_blocks(page.images[0], proximity=100)
    assert len(nearby) >= 0  # Just test it doesn't crash


# ============================================================================
# BaseStage Lifecycle Tests (NEW - test before/run/after hooks)
# ============================================================================

def test_ocr_stage_before_validates_source_images(tmp_path):
    """Test that before() hook validates source images exist."""
    # Create book structure WITHOUT source images
    scan_id = "test-book"
    book_dir = tmp_path / scan_id
    book_dir.mkdir()

    # Create metadata
    (book_dir / "metadata.json").write_text(json.dumps({
        "title": "Test Book",
        "total_pages": 5
    }))

    # Create source directory but NO images
    source_dir = book_dir / "source"
    source_dir.mkdir()

    # Initialize storage and stage
    storage = BookStorage(scan_id=scan_id, storage_root=tmp_path)
    stage = OCRStage(max_workers=2)
    checkpoint = storage.stage('ocr').checkpoint

    from infra.pipeline.logger import create_logger
    logger = create_logger(scan_id, "ocr", log_dir=tmp_path)

    # before() should raise because no source images
    with pytest.raises(FileNotFoundError) as exc_info:
        stage.before(storage, checkpoint, logger)

    assert "No source page images found" in str(exc_info.value)
    logger.close()


def test_ocr_stage_before_passes_with_source_images(tmp_path):
    """Test that before() hook passes when source images exist."""
    # Create book structure WITH source images
    scan_id = "test-book"
    book_dir = tmp_path / scan_id
    book_dir.mkdir()

    # Create metadata
    (book_dir / "metadata.json").write_text(json.dumps({
        "title": "Test Book",
        "total_pages": 3
    }))

    # Create source images
    source_dir = book_dir / "source"
    source_dir.mkdir()
    for i in range(1, 4):
        (source_dir / f"page_{i:04d}.png").write_text("fake image")

    # Initialize storage and stage
    storage = BookStorage(scan_id=scan_id, storage_root=tmp_path)
    stage = OCRStage(max_workers=2)
    checkpoint = storage.stage('ocr').checkpoint

    from infra.pipeline.logger import create_logger
    logger = create_logger(scan_id, "ocr", log_dir=tmp_path)

    # before() should pass
    stage.before(storage, checkpoint, logger)

    # Images directory should be created
    assert (book_dir / "images").exists()
    logger.close()


def test_ocr_stage_clean_via_storage(tmp_path):
    """Test that OCR outputs can be cleaned using storage API."""
    # Create book structure
    scan_id = "test-book"
    book_dir = tmp_path / scan_id
    book_dir.mkdir()

    # Create metadata
    (book_dir / "metadata.json").write_text(json.dumps({
        "title": "Test Book",
        "total_pages": 5
    }))

    # Create OCR outputs
    ocr_dir = book_dir / "ocr"
    ocr_dir.mkdir()
    for i in range(1, 6):
        (ocr_dir / f"page_{i:04d}.json").write_text(json.dumps({"page_number": i}))

    # Create checkpoint
    checkpoint_file = ocr_dir / ".checkpoint"
    checkpoint_file.write_text(json.dumps({"status": "completed"}))

    # Create images
    images_dir = book_dir / "images"
    images_dir.mkdir()
    for i in range(1, 4):
        (images_dir / f"page_{i:04d}_img_001.png").write_text("fake image")

    # Clean using storage API
    storage = BookStorage(scan_id=scan_id, storage_root=tmp_path)
    result = storage.stage('ocr').clean_stage(confirm=True)

    assert result is True
    assert not ocr_dir.exists()
    # Note: images/ is book-level, not stage-level, so it won't be cleaned by stage


# ============================================================================
# Real Production Data Tests (same as before - using fixtures)
# ============================================================================

@pytest.mark.parametrize("page_num,expected_blocks,expected_images", [
    (1, 1, 0),    # Simple title page
    (20, 4, 0),   # Complex body text with dialogue
    (215, 5, 3),  # Photo page with images
])
def test_real_ocr_outputs_validate(page_num, expected_blocks, expected_images):
    """Test that real production OCR outputs validate against schema.

    Uses actual OCR output from accidental-president book processing.
    These pages were successfully processed with 0 validation errors.
    """
    fixture_path = Path(__file__).parent.parent / "fixtures" / "ocr_outputs" / f"page_{page_num:04d}.json"

    if not fixture_path.exists():
        pytest.skip(f"Fixture not found: {fixture_path}")

    with open(fixture_path) as f:
        page_data = json.load(f)

    # Should validate without errors
    validated = OCRPageOutput(**page_data)

    # Verify basic structure
    assert validated.page_number == page_num
    assert len(validated.blocks) == expected_blocks
    assert len(validated.images) == expected_images

    # All blocks must have at least one paragraph
    assert all(len(b.paragraphs) > 0 for b in validated.blocks)

    # All paragraphs must have non-empty text
    for block in validated.blocks:
        for para in block.paragraphs:
            assert len(para.text) > 0
            assert 0.0 <= para.avg_confidence <= 1.0


def test_real_page_image_detection():
    """Test image detection results on real photo page.

    Page 215 is a photo page with 3 detected images.
    Validates that image detection logic works correctly.
    """
    fixture_path = Path(__file__).parent.parent / "fixtures" / "ocr_outputs" / "page_0215.json"

    if not fixture_path.exists():
        pytest.skip(f"Fixture not found: {fixture_path}")

    with open(fixture_path) as f:
        page_data = json.load(f)

    page = OCRPageOutput(**page_data)

    # Page 215 should have 3 images
    assert len(page.images) == 3

    # All images should have reasonable dimensions
    for img in page.images:
        assert img.bbox.width > 100, f"Image {img.image_id} too narrow: {img.bbox.width}px"
        assert img.bbox.height > 100, f"Image {img.image_id} too short: {img.bbox.height}px"

        # Aspect ratio should be reasonable (0.2 to 5.0)
        aspect_ratio = img.bbox.width / img.bbox.height
        assert 0.2 < aspect_ratio < 5.0, f"Image {img.image_id} has extreme aspect ratio: {aspect_ratio}"

        # Image should have a filename
        assert img.image_file.startswith("page_0215_img_")
        assert img.image_file.endswith(".png")


def test_real_page_hierarchical_structure():
    """Test hierarchical block/paragraph structure on complex page.

    Page 20 has 4 blocks with varying paragraph counts.
    Validates that Tesseract's hierarchical structure is preserved.
    """
    fixture_path = Path(__file__).parent.parent / "fixtures" / "ocr_outputs" / "page_0020.json"

    if not fixture_path.exists():
        pytest.skip(f"Fixture not found: {fixture_path}")

    with open(fixture_path) as f:
        page_data = json.load(f)

    page = OCRPageOutput(**page_data)

    # Page 20 has 4 blocks total
    assert len(page.blocks) == 4

    # Total paragraph count across all blocks
    total_paragraphs = sum(len(b.paragraphs) for b in page.blocks)
    assert total_paragraphs == 12

    # Block numbers should be unique
    block_nums = [b.block_num for b in page.blocks]
    assert len(block_nums) == len(set(block_nums))

    # Each block should have proper bbox hierarchy
    for block in page.blocks:
        # Block bbox should contain all its paragraphs
        for para in block.paragraphs:
            # Paragraph should be within or equal to block bounds
            assert para.bbox.x >= block.bbox.x - 5  # Allow small margin for rounding
            assert para.bbox.y >= block.bbox.y - 5


def test_real_page_helper_methods():
    """Test schema helper methods on real page data.

    Uses page 20 which has both isolated and continuous blocks.
    """
    fixture_path = Path(__file__).parent.parent / "fixtures" / "ocr_outputs" / "page_0020.json"

    if not fixture_path.exists():
        pytest.skip(f"Fixture not found: {fixture_path}")

    with open(fixture_path) as f:
        page_data = json.load(f)

    page = OCRPageOutput(**page_data)

    # Test get_all_text
    all_text = page.get_all_text()
    assert len(all_text) > 0
    assert isinstance(all_text, str)

    # Test that get_isolated_blocks + get_continuous_blocks = all blocks
    isolated = page.get_isolated_blocks()
    continuous = page.get_continuous_blocks()
    assert len(isolated) + len(continuous) == len(page.blocks)

    # Isolated blocks should have exactly 1 paragraph
    for block in isolated:
        assert len(block.paragraphs) == 1

    # Continuous blocks should have more than 1 paragraph
    for block in continuous:
        assert len(block.paragraphs) > 1
