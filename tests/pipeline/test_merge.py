"""Tests for pipeline/3_merge"""

import json
import importlib
from pathlib import Path
import pytest


# Import merge module
merge_module = importlib.import_module('pipeline.4_merge')
MergeProcessor = getattr(merge_module, 'MergeProcessor')

# Import schemas
merge_schemas = importlib.import_module('pipeline.4_merge.schemas')
MergedPageOutput = getattr(merge_schemas, 'MergedPageOutput')
MergedBlock = getattr(merge_schemas, 'MergedBlock')
MergedParagraph = getattr(merge_schemas, 'MergedParagraph')
ContinuationInfo = getattr(merge_schemas, 'ContinuationInfo')


# ============================================================================
# Schema Validation Tests
# ============================================================================

def test_schema_validation_valid_merged_page():
    """Test that valid merged page output passes schema validation."""
    valid_page = {
        "page_number": 1,
        "page_dimensions": {"width": 1000, "height": 1500},
        "blocks": [
            {
                "block_num": 1,
                "classification": "BODY",
                "classification_confidence": 0.95,
                "bbox": [100, 200, 500, 300],
                "paragraphs": [
                    {
                        "par_num": 1,
                        "text": "Test paragraph text",
                        "bbox": [100, 200, 500, 100],
                        "original_confidence": 0.90,
                        "correction_applied": True,
                        "correction_confidence": 1.0,
                        "correction_notes": "Fixed typo"
                    }
                ]
            }
        ],
        "continuation": {
            "continues_from_previous": False,
            "continues_to_next": True
        },
        "metadata": {
            "ocr_timestamp": "2025-01-01T00:00:00",
            "correction_timestamp": "2025-01-01T00:01:00",
            "correction_model": "gpt-4o",
            "merge_timestamp": "2025-01-01T00:02:00",
            "total_blocks": 1,
            "total_corrections_applied": 1
        }
    }

    # Should not raise
    validated = MergedPageOutput(**valid_page)
    assert validated.page_number == 1
    assert len(validated.blocks) == 1
    assert validated.blocks[0].paragraphs[0].text == "Test paragraph text"
    assert validated.continuation.continues_to_next is True


def test_schema_validation_requires_non_empty_text():
    """Test that paragraphs must have non-empty text."""
    invalid_page = {
        "page_number": 1,
        "page_dimensions": {"width": 1000, "height": 1500},
        "blocks": [
            {
                "block_num": 1,
                "classification": "BODY",
                "classification_confidence": 0.95,
                "bbox": [100, 200, 500, 300],
                "paragraphs": [
                    {
                        "par_num": 1,
                        "text": "",  # Empty text!
                        "bbox": [100, 200, 500, 100],
                        "original_confidence": 0.90,
                        "correction_applied": False,
                        "correction_confidence": 1.0,
                        "correction_notes": None
                    }
                ]
            }
        ],
        "continuation": {
            "continues_from_previous": False,
            "continues_to_next": False
        },
        "metadata": {
            "ocr_timestamp": "2025-01-01T00:00:00",
            "correction_timestamp": "2025-01-01T00:01:00",
            "correction_model": "gpt-4o",
            "merge_timestamp": "2025-01-01T00:02:00",
            "total_blocks": 1,
            "total_corrections_applied": 0
        }
    }

    try:
        MergedPageOutput(**invalid_page)
        assert False, "Should have raised validation error"
    except Exception as e:
        assert "at least 1 character" in str(e)


def test_schema_validation_confidence_bounds():
    """Test that confidence values are bounded [0.0, 1.0]."""
    invalid_page = {
        "page_number": 1,
        "page_dimensions": {"width": 1000, "height": 1500},
        "blocks": [
            {
                "block_num": 1,
                "classification": "BODY",
                "classification_confidence": 1.5,  # Invalid!
                "bbox": [100, 200, 500, 300],
                "paragraphs": [
                    {
                        "par_num": 1,
                        "text": "Test",
                        "bbox": [100, 200, 500, 100],
                        "original_confidence": 0.90,
                        "correction_applied": False,
                        "correction_confidence": 1.0,
                        "correction_notes": None
                    }
                ]
            }
        ],
        "continuation": {
            "continues_from_previous": False,
            "continues_to_next": False
        },
        "metadata": {
            "ocr_timestamp": "2025-01-01T00:00:00",
            "correction_timestamp": "2025-01-01T00:01:00",
            "correction_model": "gpt-4o",
            "merge_timestamp": "2025-01-01T00:02:00",
            "total_blocks": 1,
            "total_corrections_applied": 0
        }
    }

    try:
        MergedPageOutput(**invalid_page)
        assert False, "Should have raised validation error"
    except Exception as e:
        assert "less than or equal to 1" in str(e)


# ============================================================================
# Merge Logic Tests
# ============================================================================

def test_merge_handles_sparse_corrections():
    """Test merge logic handles corrections with text: null properly.

    Real correction data has many paragraphs with text: null (no correction needed).
    Merge should fall back to OCR text in these cases.
    """
    # Load real fixtures
    fixture_dir = Path(__file__).parent.parent / "fixtures"

    with open(fixture_dir / "ocr_outputs" / "page_0020.json") as f:
        ocr_data = json.load(f)

    with open(fixture_dir / "corrected_outputs" / "page_0020.json") as f:
        correction_data = json.load(f)

    # Import schemas
    ocr_schemas = importlib.import_module('pipeline.1_ocr.schemas')
    OCRPageOutput = getattr(ocr_schemas, 'OCRPageOutput')

    correction_schemas = importlib.import_module('pipeline.2_correction.schemas')
    CorrectionOutput = getattr(correction_schemas, 'CorrectionPageOutput')

    ocr_page = OCRPageOutput(**ocr_data)
    correction_page = CorrectionOutput(**correction_data)

    # Run merge
    processor = MergeProcessor(enable_checkpoints=False)
    merged_page, corrections_used, has_continuation = processor._merge_page_data(ocr_page, correction_page)

    # Validate structure
    assert merged_page['page_number'] == 20
    assert len(merged_page['blocks']) == 4

    # Check that sparse corrections work correctly
    # Block 2 has some corrected paragraphs (par 1, 2, 5) and some null (par 3, 4, 6-9)
    block_2 = next(b for b in merged_page['blocks'] if b['block_num'] == 2)

    # Paragraph 1 should be corrected (text was provided in correction)
    para_1 = next(p for p in block_2['paragraphs'] if p['par_num'] == 1)
    assert para_1['correction_applied'] is True
    assert "the Capitol" in para_1['text']
    assert para_1['correction_notes'] is not None

    # Paragraph 3 should use OCR text (correction had text: null)
    para_3 = next(p for p in block_2['paragraphs'] if p['par_num'] == 3)
    assert para_3['correction_applied'] is False
    assert para_3['text'] == ocr_data['blocks'][1]['paragraphs'][2]['text']

    # Count corrections
    assert corrections_used == 4  # Only paragraphs with non-null text


def test_merge_preserves_spatial_info():
    """Test that merge preserves OCR bounding boxes."""
    fixture_dir = Path(__file__).parent.parent / "fixtures"

    with open(fixture_dir / "ocr_outputs" / "page_0020.json") as f:
        ocr_data = json.load(f)

    with open(fixture_dir / "corrected_outputs" / "page_0020.json") as f:
        correction_data = json.load(f)

    # Import schemas
    ocr_schemas = importlib.import_module('pipeline.1_ocr.schemas')
    OCRPageOutput = getattr(ocr_schemas, 'OCRPageOutput')

    correction_schemas = importlib.import_module('pipeline.2_correction.schemas')
    CorrectionOutput = getattr(correction_schemas, 'CorrectionPageOutput')

    ocr_page = OCRPageOutput(**ocr_data)
    correction_page = CorrectionOutput(**correction_data)

    # Run merge
    processor = MergeProcessor(enable_checkpoints=False)
    merged_page, _, _ = processor._merge_page_data(ocr_page, correction_page)

    # Check that all bboxes are preserved from OCR
    for merged_block in merged_page['blocks']:
        ocr_block = next(b for b in ocr_data['blocks'] if b['block_num'] == merged_block['block_num'])

        # Block bbox should match
        assert merged_block['bbox'] == [
            ocr_block['bbox']['x'],
            ocr_block['bbox']['y'],
            ocr_block['bbox']['width'],
            ocr_block['bbox']['height']
        ]

        # Paragraph bboxes should match
        for merged_para in merged_block['paragraphs']:
            ocr_para = next(p for p in ocr_block['paragraphs'] if p['par_num'] == merged_para['par_num'])
            assert merged_para['bbox'] == [
                ocr_para['bbox']['x'],
                ocr_para['bbox']['y'],
                ocr_para['bbox']['width'],
                ocr_para['bbox']['height']
            ]


def test_merge_preserves_classification():
    """Test that merge preserves correction classifications."""
    fixture_dir = Path(__file__).parent.parent / "fixtures"

    with open(fixture_dir / "ocr_outputs" / "page_0020.json") as f:
        ocr_data = json.load(f)

    with open(fixture_dir / "corrected_outputs" / "page_0020.json") as f:
        correction_data = json.load(f)

    # Import schemas
    ocr_schemas = importlib.import_module('pipeline.1_ocr.schemas')
    OCRPageOutput = getattr(ocr_schemas, 'OCRPageOutput')

    correction_schemas = importlib.import_module('pipeline.2_correction.schemas')
    CorrectionOutput = getattr(correction_schemas, 'CorrectionPageOutput')

    ocr_page = OCRPageOutput(**ocr_data)
    correction_page = CorrectionOutput(**correction_data)

    # Run merge
    processor = MergeProcessor(enable_checkpoints=False)
    merged_page, _, _ = processor._merge_page_data(ocr_page, correction_page)

    # Check classifications are preserved
    for merged_block in merged_page['blocks']:
        corr_block = next(b for b in correction_data['blocks'] if b['block_num'] == merged_block['block_num'])
        assert merged_block['classification'] == corr_block['classification']
        assert merged_block['classification_confidence'] == corr_block['classification_confidence']


# ============================================================================
# Continuation Detection Tests
# ============================================================================

def test_detect_continuation_end_of_sentence():
    """Test continuation detection when page ends mid-sentence."""
    processor = MergeProcessor(enable_checkpoints=False)

    # Page ending with incomplete sentence (no terminal punctuation)
    blocks = [
        {
            "block_num": 1,
            "classification": "BODY",
            "paragraphs": [
                {"par_num": 1, "text": "This sentence continues"}
            ]
        }
    ]

    continuation = processor._detect_continuation(blocks)
    assert continuation['continues_to_next'] is True


def test_detect_continuation_complete_sentence():
    """Test continuation detection when page ends with complete sentence."""
    processor = MergeProcessor(enable_checkpoints=False)

    # Page ending with complete sentence
    blocks = [
        {
            "block_num": 1,
            "classification": "BODY",
            "paragraphs": [
                {"par_num": 1, "text": "This is a complete sentence."}
            ]
        }
    ]

    continuation = processor._detect_continuation(blocks)
    assert continuation['continues_to_next'] is False


def test_detect_continuation_hyphenation():
    """Test continuation detection when page ends with hyphen."""
    processor = MergeProcessor(enable_checkpoints=False)

    # Page ending with hyphenated word
    blocks = [
        {
            "block_num": 1,
            "classification": "BODY",
            "paragraphs": [
                {"par_num": 1, "text": "This word is hyphen-"}
            ]
        }
    ]

    continuation = processor._detect_continuation(blocks)
    assert continuation['continues_to_next'] is True


def test_detect_continuation_starts_lowercase():
    """Test continuation detection when page starts with lowercase (continues from previous)."""
    processor = MergeProcessor(enable_checkpoints=False)

    # Page starting mid-sentence (lowercase)
    blocks = [
        {
            "block_num": 1,
            "classification": "BODY",
            "paragraphs": [
                {"par_num": 1, "text": "continued from previous page. New sentence."}
            ]
        }
    ]

    continuation = processor._detect_continuation(blocks)
    assert continuation['continues_from_previous'] is True


def test_detect_continuation_starts_uppercase():
    """Test continuation detection when page starts with new sentence."""
    processor = MergeProcessor(enable_checkpoints=False)

    # Page starting with new sentence (uppercase)
    blocks = [
        {
            "block_num": 1,
            "classification": "BODY",
            "paragraphs": [
                {"par_num": 1, "text": "This is a new sentence."}
            ]
        }
    ]

    continuation = processor._detect_continuation(blocks)
    assert continuation['continues_from_previous'] is False


def test_detect_continuation_skips_headers():
    """Test that continuation detection skips header/footer blocks."""
    processor = MergeProcessor(enable_checkpoints=False)

    # Page with header followed by body
    blocks = [
        {
            "block_num": 1,
            "classification": "HEADER",
            "paragraphs": [
                {"par_num": 1, "text": "Chapter 1"}
            ]
        },
        {
            "block_num": 2,
            "classification": "BODY",
            "paragraphs": [
                {"par_num": 1, "text": "lowercase start"}
            ]
        }
    ]

    continuation = processor._detect_continuation(blocks)
    # Should check first BODY block, not HEADER
    assert continuation['continues_from_previous'] is True


def test_real_page_continuation():
    """Test continuation detection on real page 20 data."""
    fixture_dir = Path(__file__).parent.parent / "fixtures"

    with open(fixture_dir / "merged_outputs" / "page_0020.json") as f:
        merged_data = json.load(f)

    processor = MergeProcessor(enable_checkpoints=False)
    continuation = processor._detect_continuation(merged_data['blocks'])

    # Page 20 starts with lowercase "the Capitol" (continues from page 19)
    assert continuation['continues_from_previous'] is True

    # Page 20 ends with "gave" (no terminal punctuation, continues to page 21)
    assert continuation['continues_to_next'] is True


# ============================================================================
# Fixture-Based Integration Tests
# ============================================================================

def test_real_merged_output_validates():
    """Test that real merged output validates against schema."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "merged_outputs" / "page_0020.json"

    with open(fixture_path) as f:
        merged_data = json.load(f)

    # Should validate without errors
    validated = MergedPageOutput(**merged_data)

    # Verify basic structure
    assert validated.page_number == 20
    assert len(validated.blocks) == 4
    assert validated.metadata.total_corrections_applied == 4

    # All paragraphs must have non-empty text
    for block in validated.blocks:
        for para in block.paragraphs:
            assert len(para.text) > 0
            assert 0.0 <= para.original_confidence <= 1.0
            assert 0.0 <= para.correction_confidence <= 1.0


def test_schema_helper_methods():
    """Test helper methods on MergedPageOutput schema."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "merged_outputs" / "page_0020.json"

    with open(fixture_path) as f:
        merged_data = json.load(f)

    page = MergedPageOutput(**merged_data)

    # Test get_full_text
    full_text = page.get_full_text()
    assert len(full_text) > 0
    assert "the Capitol" in full_text
    assert "Around the globe" in full_text

    # Test get_corrected_paragraphs
    corrected = page.get_corrected_paragraphs()
    assert len(corrected) == 4  # Page 20 has 4 corrected paragraphs
    assert all(p.correction_applied for p in corrected)

    # Test get_body_blocks
    body_blocks = page.get_body_blocks()
    assert len(body_blocks) == 2  # Blocks 2 and 4 are BODY
    assert all(b.classification == "BODY" for b in body_blocks)

    # Test get_blocks_by_type
    headers = page.get_blocks_by_type("HEADER")
    assert len(headers) == 1  # Block 1 is HEADER
    assert headers[0].block_num == 1


def test_clean_stage_removes_outputs(tmp_path):
    """Test that clean_stage removes processed outputs and checkpoint."""
    # Create book structure
    scan_id = "test-book"
    book_dir = tmp_path / scan_id
    book_dir.mkdir()

    # Create metadata
    metadata_file = book_dir / "metadata.json"
    metadata_file.write_text(json.dumps({
        "title": "Test Book",
        "total_pages_processed": 10
    }))

    # Create processed outputs
    processed_dir = book_dir / "processed"
    processed_dir.mkdir()
    for i in range(1, 6):
        (processed_dir / f"page_{i:04d}.json").write_text(json.dumps({"page_number": i}))

    # Create checkpoint
    checkpoint_dir = book_dir / "checkpoints"
    checkpoint_dir.mkdir()
    (checkpoint_dir / "merge.json").write_text(json.dumps({"status": "completed"}))

    # Run clean
    processor = MergeProcessor(storage_root=tmp_path)
    result = processor.clean_stage(scan_id, confirm=True)

    assert result is True
    assert not processed_dir.exists()
    assert not (checkpoint_dir / "merge.json").exists()
