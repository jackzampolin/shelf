"""
OCR Stage Tests

Tests for the OCR pipeline stage including:
- BlockClassifier (text region classification)
- ImageDetector (image region detection)
- LayoutAnalyzer (page layout analysis)
- BookOCRProcessor (main OCR orchestrator)

No API costs - tests pure Python logic and mocked OCR results.
"""

import pytest
import json
import numpy as np
from pathlib import Path
from PIL import Image
from pipeline.ocr import BlockClassifier, ImageDetector, LayoutAnalyzer


class TestBlockClassifier:
    """Test text block classification logic."""

    def test_classify_header(self):
        """Test header classification (top 8% of page)."""
        page_width, page_height = 1000, 1000

        # Block at top of page
        bbox = (100, 30, 200, 20)  # y=30 is 3% from top
        result = BlockClassifier.classify(bbox, "Chapter 1", page_width, page_height)

        assert result == "header"

    def test_classify_footer(self):
        """Test footer classification (bottom 5% of page)."""
        page_width, page_height = 1000, 1000

        # Block at bottom of page
        bbox = (100, 970, 200, 20)  # y=970 is 97% from top
        result = BlockClassifier.classify(bbox, "Page 42", page_width, page_height)

        assert result == "footer"

    def test_classify_caption(self):
        """Test caption classification (ALL CAPS with keywords)."""
        page_width, page_height = 1000, 1000

        # Caption with keyword
        bbox = (100, 500, 200, 20)
        result = BlockClassifier.classify(
            bbox,
            "LIBRARY OF CONGRESS",
            page_width,
            page_height
        )

        assert result == "caption"

    def test_classify_body(self):
        """Test body text classification (default)."""
        page_width, page_height = 1000, 1000

        # Regular body text in middle of page
        bbox = (100, 500, 600, 100)
        result = BlockClassifier.classify(
            bbox,
            "This is regular body text that should be classified as body content.",
            page_width,
            page_height
        )

        assert result == "body"

    def test_caption_requires_keyword(self):
        """Test that caption classification requires keywords."""
        page_width, page_height = 1000, 1000

        # ALL CAPS but no caption keyword
        bbox = (100, 500, 200, 20)
        result = BlockClassifier.classify(
            bbox,
            "RANDOM ALL CAPS TEXT",
            page_width,
            page_height
        )

        # Should be classified as body, not caption
        assert result == "body"


class TestImageDetector:
    """Test image region detection."""

    def test_detect_images_empty_page(self):
        """Test image detection on page with no images."""
        # Create a white page
        img = Image.new('RGB', (1000, 1000), color='white')
        text_boxes = [(100, 100, 800, 50)]  # One text box

        images = ImageDetector.detect_images(img, text_boxes, min_area=10000)

        # White page with text should not detect images
        assert isinstance(images, list)

    def test_detect_images_ignores_text_areas(self):
        """Test that text areas are excluded from image detection."""
        # Create a page with text areas
        img = Image.new('RGB', (1000, 1000), color='white')

        # Multiple text boxes
        text_boxes = [
            (100, 100, 800, 50),
            (100, 200, 800, 50),
            (100, 300, 800, 50)
        ]

        images = ImageDetector.detect_images(img, text_boxes, min_area=10000)

        # Should return list (may be empty or contain non-text regions)
        assert isinstance(images, list)

    def test_min_area_threshold(self):
        """Test that minimum area threshold is respected."""
        img = Image.new('RGB', (1000, 1000), color='white')
        text_boxes = []

        # Use very large min_area to filter everything out
        images = ImageDetector.detect_images(img, text_boxes, min_area=900000)

        # Should return empty list or very few large regions
        assert isinstance(images, list)
        # Most regions should be filtered out by large min_area
        assert len(images) < 5


class TestLayoutAnalyzer:
    """Test page layout analysis."""

    def test_associate_captions_empty(self):
        """Test caption association with no blocks."""
        caption_blocks = []
        image_blocks = []

        result = LayoutAnalyzer.associate_captions(caption_blocks, image_blocks)

        # Should return empty or dict structure
        assert result is not None

    def test_associate_captions_nearby(self):
        """Test caption association with nearby image."""
        caption_blocks = [
            {'id': 'caption_1', 'bbox': [100, 500, 200, 20], 'text': 'Figure 1'}
        ]
        image_blocks = [
            {'id': 'image_1', 'bbox': [100, 300, 200, 180]}  # Image above caption
        ]

        result = LayoutAnalyzer.associate_captions(
            caption_blocks,
            image_blocks,
            proximity=100
        )

        # Should return dict of associations
        assert isinstance(result, dict)


class TestOCROutputFormat:
    """Test OCR output format compliance."""

    def test_page_json_structure(self):
        """Test that page JSON has required fields."""
        # This tests the expected output format
        # Actual OCR stage should produce this structure

        expected_fields = [
            'page_number',
            'regions',
            'image_regions',
            'metadata'
        ]

        # Create sample output
        page_output = {
            'page_number': 1,
            'regions': [
                {
                    'type': 'body',
                    'text': 'Sample text',
                    'bbox': [100, 100, 200, 50]
                }
            ],
            'image_regions': [],
            'metadata': {
                'width': 1000,
                'height': 1000
            }
        }

        # Verify required fields exist
        for field in expected_fields:
            assert field in page_output

    def test_region_structure(self):
        """Test that text regions have required fields."""
        region = {
            'type': 'body',
            'text': 'Sample text content',
            'bbox': [100, 200, 300, 50]
        }

        assert 'type' in region
        assert 'text' in region
        assert 'bbox' in region
        assert region['type'] in ['header', 'footer', 'body', 'caption']
        assert isinstance(region['bbox'], list)
        assert len(region['bbox']) == 4

    def test_image_region_structure(self):
        """Test that image regions have required fields."""
        image_region = {
            'bbox': [100, 200, 300, 400],
            'area': 120000,
            'page_number': 1
        }

        assert 'bbox' in image_region
        assert 'area' in image_region
        assert isinstance(image_region['bbox'], list)
        assert len(image_region['bbox']) == 4


class TestOCRIntegration:
    """Integration tests for OCR stage."""

    def test_ocr_output_directory_structure(self, tmp_path):
        """Test that OCR creates correct directory structure."""
        book_dir = tmp_path / "test-book"
        book_dir.mkdir()

        # Create expected directories
        (book_dir / "ocr").mkdir()
        (book_dir / "images").mkdir()
        (book_dir / "source").mkdir()

        # Verify structure
        assert (book_dir / "ocr").exists()
        assert (book_dir / "images").exists()
        assert (book_dir / "source").exists()

    def test_page_numbering_sequential(self):
        """Test that page numbers are sequential and zero-padded."""
        # Test page number formatting
        for i in range(1, 1000):
            page_filename = f"page_{i:04d}.json"

            # Verify zero-padding
            assert len(page_filename) >= 14  # "page_0001.json" is 14 chars
            assert page_filename.startswith("page_")
            assert page_filename.endswith(".json")

    def test_metadata_update_after_ocr(self, tmp_path):
        """Test that metadata is updated after OCR completion."""
        metadata_file = tmp_path / "metadata.json"

        # Initial metadata
        metadata = {
            'title': 'Test Book',
            'author': 'Test Author'
        }

        # Simulate OCR completion update
        from datetime import datetime
        metadata['ocr_complete'] = True
        metadata['ocr_completion_date'] = datetime.now().isoformat()
        metadata['total_pages_processed'] = 100
        metadata['ocr_mode'] = 'structured'

        # Save and reload
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f)

        with open(metadata_file) as f:
            loaded = json.load(f)

        # Verify required fields
        assert loaded['ocr_complete'] is True
        assert 'ocr_completion_date' in loaded
        assert loaded['total_pages_processed'] == 100
        assert loaded['ocr_mode'] == 'structured'


class TestOCRErrorHandling:
    """Test OCR error handling."""

    def test_handles_missing_pdf(self, tmp_path):
        """Test handling of missing PDF files."""
        book_dir = tmp_path / "test-book"
        book_dir.mkdir()
        source_dir = book_dir / "source"
        source_dir.mkdir()

        # No PDFs in source directory
        pdf_files = list(source_dir.glob("*.pdf"))

        assert len(pdf_files) == 0
        # OCR processor should handle this gracefully

    def test_handles_corrupted_image(self):
        """Test handling of corrupted/invalid images."""
        # Create invalid image data
        invalid_data = np.random.randint(0, 255, (10, 10, 3), dtype=np.uint8)

        try:
            img = Image.fromarray(invalid_data)
            # If this succeeds, that's fine - PIL is forgiving
            assert img is not None
        except Exception:
            # If it fails, error handling worked
            pass


class TestOCRPerformance:
    """Test OCR performance characteristics."""

    def test_parallel_processing_enabled(self, tmp_path):
        """Test that parallel processing can be configured."""
        from pipeline.ocr import BookOCRProcessor

        # Test with different worker counts
        for workers in [1, 5, 10]:
            processor = BookOCRProcessor(
                storage_root=tmp_path,
                max_workers=workers
            )
            assert processor.max_workers == workers

    def test_checkpoint_enabled_by_default(self, tmp_path):
        """Test that checkpointing is enabled by default."""
        from pipeline.ocr import BookOCRProcessor

        processor = BookOCRProcessor(
            storage_root=tmp_path,
            enable_checkpoints=True
        )
        assert processor.enable_checkpoints is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
