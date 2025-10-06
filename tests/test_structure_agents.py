"""
Test structure stage agents on real Roosevelt autobiography data.

Uses actual corrected pages from ~/Documents/book_scans/roosevelt-autobiography/
to test the 3-agent extraction pattern.

Cost per run: ~$0.05 (10 pages through gpt-4o-mini)
"""

import pytest
import json
from pathlib import Path
from pipeline.structure.agents import (
    extract_batch,
    verify_extraction_simple,
    reconcile_overlaps,
    text_similarity
)


# Roosevelt autobiography pages for testing
ROOSEVELT_DIR = Path.home() / "Documents" / "book_scans" / "roosevelt-autobiography" / "corrected"

# Test pages: 75-84 (10 pages - production batch size)
TEST_PAGES = list(range(75, 85))


def load_roosevelt_pages(page_numbers):
    """Load Roosevelt pages from corrected directory."""
    pages = []

    for page_num in page_numbers:
        page_file = ROOSEVELT_DIR / f"page_{page_num:04d}.json"

        if not page_file.exists():
            pytest.skip(f"Roosevelt test data not available: {page_file}")

        with open(page_file) as f:
            page_data = json.load(f)

        pages.append(page_data)

    return pages


@pytest.mark.skipif(
    not ROOSEVELT_DIR.exists(),
    reason="Roosevelt autobiography test data not available"
)
@pytest.mark.api
@pytest.mark.slow
def test_extract_agent_on_roosevelt_batch():
    """Test extract agent on 10 Roosevelt pages (production batch size)."""
    pages = load_roosevelt_pages(TEST_PAGES)

    # Run extraction (will take ~1-2 minutes for 10 pages)
    result = extract_batch(pages)

    # Verify result structure
    assert 'clean_text' in result
    assert 'paragraphs' in result
    assert 'word_count' in result
    assert 'scan_pages' in result

    # Verify content
    assert len(result['clean_text']) > 100, "Should have substantial extracted text"
    assert result['word_count'] > 0, "Should have non-zero word count"
    assert result['scan_pages'] == TEST_PAGES, "Should track all scan pages"

    # Check paragraphs
    assert len(result['paragraphs']) > 0, "Should have extracted paragraphs"

    # Each paragraph should have required fields
    for para in result['paragraphs']:
        assert 'text' in para
        assert 'scan_page' in para
        assert 'type' in para
        # LLM might return scan_page as string or int, handle both
        page = para['scan_page'] if isinstance(para['scan_page'], int) else int(para['scan_page'])
        assert page in TEST_PAGES, f"Paragraph page {page} should be in batch {TEST_PAGES}"

    print(f"\n✓ Extracted {result['word_count']} words from {len(TEST_PAGES)} pages")
    print(f"✓ Found {len(result['paragraphs'])} paragraphs")
    print(f"✓ Removed header pattern: {result.get('running_header_pattern', 'none')}")

    # Verify we got reasonable text extraction from 10 pages
    # Roosevelt pages average ~500 words/page, so 10 pages = ~5000 words
    # After header removal, expect 60-90% = 3000-4500 words
    assert result['word_count'] > 2000, f"Should extract substantial content from 10 pages, got {result['word_count']}"


@pytest.mark.skipif(
    not ROOSEVELT_DIR.exists(),
    reason="Roosevelt autobiography test data not available"
)
def test_verify_agent_simple():
    """Test verification logic with real Roosevelt data and mock extraction."""
    pages = load_roosevelt_pages(TEST_PAGES[:5])  # Use 5 pages

    # Create a mock extraction result with very low word count
    extraction_result = {
        'clean_text': "Test content here",
        'paragraphs': [
            {'text': 'Test content here', 'scan_page': 75, 'type': 'body'}
        ],
        'word_count': 3,
        'scan_pages': [75, 76, 77, 78, 79]
    }

    # Run simple verification (no LLM call)
    verification = verify_extraction_simple(pages, extraction_result)

    # Should detect excessive content loss
    assert verification['word_count_ratio'] < 0.60, "Should detect excessive content loss"
    assert not verification['word_count_ok'], "Should flag as not OK"

    print(f"\n✓ Verification detected content loss: {verification['word_count_ratio']:.1%} retained")


def test_reconcile_agent_consensus():
    """Test reconciliation logic when extractions match."""
    # Create two identical extractions
    extraction1 = {
        'clean_text': "This is a test paragraph about Roosevelt's presidency.\n\nAnother paragraph here.",
        'paragraphs': [
            {'text': "This is a test paragraph about Roosevelt's presidency.", 'scan_page': 80, 'type': 'body'},
            {'text': "Another paragraph here.", 'scan_page': 81, 'type': 'body'}
        ],
        'word_count': 13,
        'scan_pages': [78, 79, 80, 81, 82, 83, 84]
    }

    extraction2 = {
        'clean_text': "This is a test paragraph about Roosevelt's presidency.\n\nAnother paragraph here.",
        'paragraphs': [
            {'text': "This is a test paragraph about Roosevelt's presidency.", 'scan_page': 80, 'type': 'body'},
            {'text': "Another paragraph here.", 'scan_page': 81, 'type': 'body'}
        ],
        'word_count': 13,
        'scan_pages': [80, 81, 82, 83, 84, 85, 86, 87]
    }

    overlap_pages = [80, 81, 82, 83, 84]

    # Reconcile
    reconciliation = reconcile_overlaps(extraction1, extraction2, overlap_pages)

    # Should achieve consensus
    assert reconciliation['status'] == 'consensus'
    assert reconciliation['similarity'] >= 0.95
    assert reconciliation['confidence'] == 'high'
    assert reconciliation['resolution_method'] == 'consensus'


def test_reconcile_agent_disagreement():
    """Test reconciliation logic when extractions differ."""
    extraction1 = {
        'clean_text': "This is version A of the text.",
        'paragraphs': [
            {'text': "This is version A of the text.", 'scan_page': 80, 'type': 'body'}
        ],
        'word_count': 7,
        'scan_pages': [78, 79, 80, 81, 82]
    }

    extraction2 = {
        'clean_text': "This is version B with different content entirely.",
        'paragraphs': [
            {'text': "This is version B with different content entirely.", 'scan_page': 80, 'type': 'body'}
        ],
        'word_count': 8,
        'scan_pages': [80, 81, 82, 83, 84]
    }

    overlap_pages = [80, 81, 82]

    # Reconcile
    reconciliation = reconcile_overlaps(extraction1, extraction2, overlap_pages)

    # Should detect disagreement
    assert reconciliation['status'] == 'disagreement'
    assert reconciliation['similarity'] < 0.95
    assert reconciliation['confidence'] == 'low'
    assert reconciliation['needs_review']


def test_text_similarity():
    """Test text similarity calculation."""
    # Identical texts
    text1 = "The quick brown fox jumps over the lazy dog."
    text2 = "The quick brown fox jumps over the lazy dog."
    assert text_similarity(text1, text2) == 1.0

    # Completely different texts
    text3 = "Something entirely different."
    assert text_similarity(text1, text3) < 0.5

    # Similar but not identical
    text4 = "The quick brown fox jumped over the lazy dog."
    sim = text_similarity(text1, text4)
    assert 0.8 < sim < 1.0
