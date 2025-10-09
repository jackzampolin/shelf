"""Tests for pipeline/1_ocr"""

import json
import importlib
from pathlib import Path


# Import OCR module
ocr_module = importlib.import_module('pipeline.1_ocr')
BookOCRProcessor = getattr(ocr_module, 'BookOCRProcessor')
OCRPageOutput = getattr(ocr_module, 'OCRPageOutput')


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


def test_clean_stage_removes_outputs(tmp_path):
    """Test that clean_stage removes OCR outputs and checkpoint."""
    # Create book structure
    scan_id = "test-book"
    book_dir = tmp_path / scan_id
    book_dir.mkdir()

    # Create metadata
    metadata_file = book_dir / "metadata.json"
    metadata_file.write_text(json.dumps({
        "title": "Test Book",
        "ocr_complete": True,
        "total_pages_processed": 10
    }))

    # Create OCR outputs
    ocr_dir = book_dir / "ocr"
    ocr_dir.mkdir()
    for i in range(1, 6):
        (ocr_dir / f"page_{i:04d}.json").write_text(json.dumps({"page_number": i}))

    # Create images
    images_dir = book_dir / "images"
    images_dir.mkdir()
    for i in range(1, 4):
        (images_dir / f"page_{i:04d}_img_001.png").write_text("fake image")

    # Create checkpoint
    checkpoint_dir = book_dir / "checkpoints"
    checkpoint_dir.mkdir()
    (checkpoint_dir / "ocr.json").write_text(json.dumps({"status": "completed"}))

    # Run clean
    processor = BookOCRProcessor(storage_root=tmp_path)
    result = processor.clean_stage(scan_id, confirm=True)

    assert result is True
    assert not ocr_dir.exists()
    assert not images_dir.exists()
    assert not (checkpoint_dir / "ocr.json").exists()

    # Check metadata was reset
    with open(metadata_file) as f:
        metadata = json.load(f)
        assert metadata["ocr_complete"] is False
        assert "total_pages_processed" not in metadata


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
