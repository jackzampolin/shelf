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
from pipeline.structure.extractor import ExtractionOrchestrator


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


@pytest.mark.skipif(
    not ROOSEVELT_DIR.exists(),
    reason="Roosevelt autobiography test data not available"
)
@pytest.mark.api
@pytest.mark.slow
def test_extractor_orchestrator_on_roosevelt_sample():
    """
    Test full extractor orchestrator on Roosevelt pages 75-90.

    This tests the complete sliding window extraction pipeline:
    - Batch creation with overlap
    - Parallel processing
    - 3-agent coordination (extract → verify)
    - Overlap reconciliation

    Expected: 2 batches (pages 75-84 and 82-90 with 3-page overlap)
    Cost: ~$0.02
    """
    orchestrator = ExtractionOrchestrator(
        scan_id="roosevelt-autobiography",
        window_size=10,
        overlap=3,
        max_workers=30
    )

    # Run extraction on sample pages
    results = orchestrator.extract_sliding_window(start_page=75, end_page=90)

    # Verify results structure
    assert len(results) == 2, "Should create 2 batches for 16 pages"

    # Check batch 0 (pages 75-84)
    batch0 = results[0]
    assert batch0['status'] == 'success'
    assert batch0['batch_id'] == 0
    assert batch0['batch_metadata']['start_page'] == 75
    assert batch0['batch_metadata']['end_page'] == 84
    assert batch0['result']['scan_pages'] == list(range(75, 85))

    # Check batch 1 (pages 82-90, overlaps with batch 0 on pages 82-84)
    batch1 = results[1]
    assert batch1['status'] == 'success'
    assert batch1['batch_id'] == 1
    assert batch1['batch_metadata']['start_page'] == 82
    assert batch1['batch_metadata']['end_page'] == 90
    assert batch1['result']['scan_pages'] == list(range(82, 91))
    assert batch1['batch_metadata']['overlap_with_prev'] == [82, 83, 84]

    # Verify reconciliation happened
    assert 'reconciliation' in batch1
    reconciliation = batch1['reconciliation']
    assert 'status' in reconciliation
    assert 'similarity' in reconciliation
    assert reconciliation['overlap_pages'] == [82, 83, 84]

    # Verify extraction quality
    assert batch0['result']['word_count'] > 1000, "Should extract substantial content"
    assert batch1['result']['word_count'] > 1000, "Should extract substantial content"

    # Verify cost tracking
    assert batch0['cost'] > 0
    assert batch1['cost'] > 0

    print(f"\n✓ Batch 0: {batch0['result']['word_count']} words from pages {batch0['batch_metadata']['start_page']}-{batch0['batch_metadata']['end_page']}")
    print(f"✓ Batch 1: {batch1['result']['word_count']} words from pages {batch1['batch_metadata']['start_page']}-{batch1['batch_metadata']['end_page']}")
    print(f"✓ Overlap reconciliation: {reconciliation['status']} (similarity: {reconciliation['similarity']:.2%})")
    print(f"✓ Total cost: ${batch0['cost'] + batch1['cost']:.2f}")
