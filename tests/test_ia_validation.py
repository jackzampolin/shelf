"""
Internet Archive validation tests.

Compares Scanshelf pipeline outputs against IA ABBYY ground truth data.

This test is marked as 'e2e' and 'slow' because:
- Requires full Roosevelt book to be processed
- Compares against large ground truth dataset
- Should not run in regular CI (run manually before releases)

Usage:
    # Run validation on specific page range
    pytest tests/test_ia_validation.py::test_ocr_validation_sample -v -s

    # Run full validation (all pages)
    pytest tests/test_ia_validation.py::test_ocr_validation_full -v -s --e2e
"""

import json
import pytest
from pathlib import Path

from tests.validation.abbyy_parser import ABBYYParser
from tests.validation.comparison import (
    compare_page_texts,
    aggregate_accuracy,
    format_aggregate_report,
    format_accuracy_report,
)


# Paths
ROOSEVELT_SCAN_DIR = Path.home() / "Documents" / "book_scans" / "roosevelt-autobiography"
IA_GROUND_TRUTH = Path(__file__).parent / "fixtures" / "roosevelt" / "ia_ground_truth" / "abbyy.gz"


def load_scanshelf_page_text(scan_dir: Path, page_num: int, stage: str = "ocr") -> str:
    """
    Load text from Scanshelf pipeline output.

    Args:
        scan_dir: Root directory for scan (e.g., roosevelt-autobiography/)
        page_num: Page number (1-indexed)
        stage: Pipeline stage ("ocr", "corrected", etc.)

    Returns:
        Extracted text from the page
    """
    # Map stage names to directory names
    stage_dirs = {
        "ocr": "ocr",
        "corrected": "corrected",
        "fix": "corrected",  # Fix stage overwrites corrected
    }

    stage_dir = stage_dirs.get(stage, stage)
    page_file = scan_dir / stage_dir / f"page_{page_num:04d}.json"

    if not page_file.exists():
        raise FileNotFoundError(f"Page file not found: {page_file}")

    with open(page_file) as f:
        data = json.load(f)

    # Extract text from regions
    texts = []
    for region in data.get('regions', []):
        if region.get('type') in ['body', 'header', 'footer']:
            text = region.get('text', '')
            if text:
                texts.append(text)

    return ' '.join(texts)


@pytest.mark.skip(reason="Roosevelt book not in test fixtures")
def test_ocr_validation_sample():
    """
    Validate OCR stage output against IA ground truth (sample pages).

    Tests pages 10-20 as a representative sample.
    This test runs quickly and doesn't require full pipeline run.
    """
    # Check prerequisites
    if not ROOSEVELT_SCAN_DIR.exists():
        pytest.skip("Roosevelt book not found at ~/Documents/book_scans/roosevelt-autobiography")

    if not IA_GROUND_TRUTH.exists():
        pytest.skip("IA ground truth not found in test fixtures")

    # Initialize parser
    parser = ABBYYParser(IA_GROUND_TRUTH)

    # Test pages 10-20 (representative sample)
    start_page = 10
    end_page = 20

    print(f"\n{'='*60}")
    print(f"OCR Validation: Pages {start_page}-{end_page}")
    print(f"{'='*60}\n")

    results = []

    for page_num in range(start_page, end_page + 1):
        try:
            # Load our OCR output
            our_text = load_scanshelf_page_text(ROOSEVELT_SCAN_DIR, page_num, stage="ocr")

            # Load IA ground truth
            ia_text = parser.get_page_text(page_num)

            # Compare
            result = compare_page_texts(our_text, ia_text, page_num, stage="OCR")
            results.append(result)

            # Print individual page report
            print(f"\nPage {page_num}:")
            print(f"  CER: {result['cer']:.2%}")
            print(f"  Character Accuracy: {result['character_accuracy']:.2%}")
            print(f"  WER: {result['wer']:.2%}")
            print(f"  Characters: {result['char_count']}")

        except Exception as e:
            print(f"\nPage {page_num}: Error - {e}")
            continue

    # Aggregate results
    if results:
        aggregate = aggregate_accuracy(results)
        print(format_aggregate_report(aggregate, "OCR Stage - Sample Pages"))

        # Assert quality thresholds
        # Target: >90% accuracy for raw OCR (before correction)
        assert aggregate['avg_character_accuracy'] > 0.85, \
            f"OCR accuracy too low: {aggregate['avg_character_accuracy']:.2%}"

        print("\n✅ OCR validation passed!")
    else:
        pytest.fail("No pages successfully validated")


@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.skip(reason="Full validation expensive - run manually")
def test_ocr_validation_full():
    """
    Validate OCR stage across all pages.

    This is a comprehensive validation that:
    - Tests all pages with OCR output
    - Generates detailed accuracy report
    - Should be run manually before releases

    Expected runtime: ~5-10 minutes (reading files only, no API calls)
    """
    # Check prerequisites
    if not ROOSEVELT_SCAN_DIR.exists():
        pytest.skip("Roosevelt book not found")

    if not IA_GROUND_TRUTH.exists():
        pytest.skip("IA ground truth not found")

    # Initialize parser
    parser = ABBYYParser(IA_GROUND_TRUTH)
    total_pages = parser.get_page_count()

    print(f"\n{'='*60}")
    print(f"Full OCR Validation: All {total_pages} pages")
    print(f"{'='*60}\n")

    results = []
    errors = []

    for page_num in range(1, total_pages + 1):
        try:
            # Load our OCR output
            our_text = load_scanshelf_page_text(ROOSEVELT_SCAN_DIR, page_num, stage="ocr")

            # Load IA ground truth
            ia_text = parser.get_page_text(page_num)

            # Skip empty pages
            if not ia_text.strip():
                continue

            # Compare
            result = compare_page_texts(our_text, ia_text, page_num, stage="OCR")
            results.append(result)

            # Progress update every 50 pages
            if page_num % 50 == 0:
                print(f"Progress: {page_num}/{total_pages} pages")

        except FileNotFoundError:
            # Page not yet processed
            continue
        except Exception as e:
            errors.append((page_num, str(e)))
            continue

    # Aggregate results
    if results:
        aggregate = aggregate_accuracy(results)
        print(format_aggregate_report(aggregate, "OCR Stage - Full Book"))

        # Print worst 10 pages for investigation
        sorted_results = sorted(results, key=lambda x: x['cer'], reverse=True)
        print("\nWorst 10 Pages (highest CER):")
        for i, result in enumerate(sorted_results[:10], 1):
            print(f"  {i}. Page {result['page_num']}: CER {result['cer']:.2%}")

        # Assert quality thresholds
        assert aggregate['avg_character_accuracy'] > 0.85, \
            f"OCR accuracy too low: {aggregate['avg_character_accuracy']:.2%}"

        print(f"\n✅ Full OCR validation passed!")
        print(f"   Pages validated: {len(results)}")
        print(f"   Pages with errors: {len(errors)}")
    else:
        pytest.fail("No pages successfully validated")


@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.skip(reason="Requires corrected stage - run manually")
def test_corrected_validation_sample():
    """
    Validate Correct stage output against IA ground truth (sample pages).

    Tests pages 10-20 after LLM correction.
    Expected improvement: 85% -> 95%+ accuracy.
    """
    # Check prerequisites
    if not ROOSEVELT_SCAN_DIR.exists():
        pytest.skip("Roosevelt book not found")

    if not IA_GROUND_TRUTH.exists():
        pytest.skip("IA ground truth not found")

    # Initialize parser
    parser = ABBYYParser(IA_GROUND_TRUTH)

    # Test pages 10-20
    start_page = 10
    end_page = 20

    print(f"\n{'='*60}")
    print(f"Corrected Stage Validation: Pages {start_page}-{end_page}")
    print(f"{'='*60}\n")

    results = []

    for page_num in range(start_page, end_page + 1):
        try:
            # Load our corrected output
            our_text = load_scanshelf_page_text(
                ROOSEVELT_SCAN_DIR, page_num, stage="corrected"
            )

            # Load IA ground truth
            ia_text = parser.get_page_text(page_num)

            # Compare
            result = compare_page_texts(our_text, ia_text, page_num, stage="Corrected")
            results.append(result)

            print(f"\nPage {page_num}:")
            print(f"  CER: {result['cer']:.2%}")
            print(f"  Character Accuracy: {result['character_accuracy']:.2%}")

        except Exception as e:
            print(f"\nPage {page_num}: Error - {e}")
            continue

    # Aggregate results
    if results:
        aggregate = aggregate_accuracy(results)
        print(format_aggregate_report(aggregate, "Corrected Stage - Sample Pages"))

        # Assert improved quality thresholds
        # Target: >95% accuracy after LLM correction
        assert aggregate['avg_character_accuracy'] > 0.93, \
            f"Corrected accuracy too low: {aggregate['avg_character_accuracy']:.2%}"

        print("\n✅ Corrected stage validation passed!")
    else:
        pytest.fail("No pages successfully validated")


def test_parser_functionality():
    """
    Test that ABBYY parser works correctly.

    This test runs quickly and doesn't require Roosevelt book.
    """
    if not IA_GROUND_TRUTH.exists():
        pytest.skip("IA ground truth not found")

    parser = ABBYYParser(IA_GROUND_TRUTH)

    # Basic functionality tests
    assert parser.get_page_count() > 0, "Should have pages"

    # Test page 10 (known to have content)
    text = parser.get_page_text(10)
    assert len(text) > 0, "Page 10 should have text"

    meta = parser.get_page_metadata(10)
    assert meta['width'] > 0
    assert meta['height'] > 0
    assert meta['resolution'] > 0

    conf = parser.get_page_confidence_scores(10)
    assert 0 <= conf['avg_confidence'] <= 100
    assert 0 <= conf['min_confidence'] <= 100

    print("\n✅ ABBYY parser tests passed!")
