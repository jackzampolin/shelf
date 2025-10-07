"""
Correct Stage Tests

Tests for the LLM correction pipeline stage including:
- RateLimiter (API throttling)
- StructuredPageCorrector (main orchestrator)
- Agent 1 (error detection)
- Agent 2 (correction application)
- Agent 3 (verification)
- Correction application to regions
- Checkpoint integration

Test Organization:
- Unit tests: Use committed fixtures (roosevelt_fixtures)
- Integration tests: Use full book (roosevelt_full_book)
- API tests: Real LLM calls (~$0.02-0.05 per run)

Run patterns:
- pytest -m unit: Fast unit tests with committed fixtures
- pytest -m integration: Full book integration tests
- pytest -m api: Tests that make real API calls
"""

import pytest
import json
import time
import shutil
from pathlib import Path
from pipeline.correct import (
    RateLimiter,
    StructuredPageCorrector
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_ocr_page(roosevelt_fixtures):
    """Load a real OCR page from Roosevelt fixtures."""
    ocr_file = roosevelt_fixtures / "ocr" / "page_0010.json"
    with open(ocr_file) as f:
        return json.load(f)


@pytest.fixture
def sample_corrected_page(roosevelt_fixtures):
    """Load a real corrected page from Roosevelt fixtures."""
    corrected_file = roosevelt_fixtures / "corrected" / "page_0010.json"
    with open(corrected_file) as f:
        return json.load(f)


@pytest.fixture
def temp_test_book(tmp_path, roosevelt_full_book):
    """Create a temporary test book with a few Roosevelt pages for testing."""
    if roosevelt_full_book is None:
        pytest.skip("Full Roosevelt book required for this test")

    test_book = tmp_path / "test-roosevelt"
    test_book.mkdir()

    # Create directory structure
    (test_book / "ocr").mkdir()
    (test_book / "corrected").mkdir()
    (test_book / "needs_review").mkdir()
    (test_book / "logs").mkdir()
    (test_book / "source").mkdir()

    # Copy a few OCR pages for testing (pages 10-12)
    for page_num in range(10, 13):
        src = roosevelt_full_book / "ocr" / f"page_{page_num:04d}.json"
        if src.exists():
            dst = test_book / "ocr" / f"page_{page_num:04d}.json"
            shutil.copy(src, dst)

    # Create minimal metadata
    metadata = {
        "title": "Roosevelt Test",
        "author": "Theodore Roosevelt",
        "total_pages": 3
    }
    with open(test_book / "metadata.json", 'w') as f:
        json.dump(metadata, f)

    return test_book


# ============================================================================
# RATE LIMITER TESTS
# ============================================================================

@pytest.mark.unit
class TestRateLimiter:
    """Test API rate limiting."""

    def test_rate_limiter_initialization(self):
        """Test RateLimiter initializes with correct parameters."""
        limiter = RateLimiter(calls_per_minute=60)

        assert limiter.calls_per_minute == 60
        assert limiter.min_interval == 1.0  # 60 calls / 60 seconds
        assert limiter.last_call == 0

    def test_rate_limiter_enforces_delay(self):
        """Test that RateLimiter actually delays calls."""
        limiter = RateLimiter(calls_per_minute=120)  # 0.5s between calls

        # First call should be immediate
        start = time.time()
        limiter.wait()
        first_duration = time.time() - start
        assert first_duration < 0.1  # Should be essentially instant

        # Second call should be delayed
        start = time.time()
        limiter.wait()
        second_duration = time.time() - start
        assert 0.4 < second_duration < 0.6  # Should wait ~0.5s

    def test_rate_limiter_thread_safe(self):
        """Test RateLimiter works with multiple threads."""
        limiter = RateLimiter(calls_per_minute=60)

        # Simulate concurrent calls
        import threading
        results = []

        def make_call(call_id):
            start = time.time()
            limiter.wait()
            duration = time.time() - start
            results.append((call_id, duration))

        threads = [threading.Thread(target=make_call, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have 3 results
        assert len(results) == 3


# ============================================================================
# STRUCTURED PAGE CORRECTOR TESTS
# ============================================================================

@pytest.mark.unit
class TestStructuredPageCorrector:
    """Test main correction orchestrator."""

    def test_corrector_initialization(self, tmp_path):
        """Test StructuredPageCorrector initializes correctly."""
        # Create book directory first
        book_dir = tmp_path / "test-book"
        book_dir.mkdir()

        corrector = StructuredPageCorrector(
            book_title="test-book",
            storage_root=tmp_path,
            model="openai/gpt-4o-mini",
            max_workers=10,
            calls_per_minute=60,
            enable_checkpoints=False
        )

        assert corrector.book_title == "test-book"
        assert corrector.model == "openai/gpt-4o-mini"
        assert corrector.max_workers == 10
        assert corrector.rate_limiter.calls_per_minute == 60
        assert corrector.checkpoint is None  # Disabled

    def test_corrector_creates_directories(self, tmp_path):
        """Test that corrector creates required directories."""
        # Create book directory first
        book_dir = tmp_path / "test-book"
        book_dir.mkdir()

        corrector = StructuredPageCorrector(
            book_title="test-book",
            storage_root=tmp_path,
            enable_checkpoints=False
        )

        book_dir = tmp_path / "test-book"
        assert (book_dir / "corrected").exists()
        assert (book_dir / "needs_review").exists()
        assert (book_dir / "logs").exists()
        assert (book_dir / "logs" / "debug").exists()

    def test_filter_correctable_regions(self, sample_ocr_page, tmp_path):
        """Test filtering of correctable text regions."""
        # Create test book directory
        book_dir = tmp_path / "test"
        book_dir.mkdir()

        corrector = StructuredPageCorrector(
            book_title="test",
            storage_root=tmp_path,
            enable_checkpoints=False
        )

        correctable = corrector.filter_correctable_regions(sample_ocr_page)

        # Should only include header, body, caption (not footer, not image)
        for region in correctable:
            assert region['type'] in ['header', 'body', 'caption']

    def test_build_page_text(self, sample_ocr_page, tmp_path):
        """Test building text from regions in reading order."""
        # Create test book directory
        book_dir = tmp_path / "test"
        book_dir.mkdir()

        corrector = StructuredPageCorrector(
            book_title="test",
            storage_root=tmp_path,
            enable_checkpoints=False
        )

        text = corrector.build_page_text(sample_ocr_page)

        assert isinstance(text, str)
        assert len(text) > 0
        # Should not include image regions
        assert '[image]' not in text.lower()

    @pytest.mark.integration
    def test_get_page_context(self, roosevelt_full_book):
        """Test loading page with context from adjacent pages (integration test)."""
        if roosevelt_full_book is None:
            pytest.skip("Full Roosevelt book required for integration test")

        corrector = StructuredPageCorrector(
            book_title="roosevelt-autobiography",
            storage_root=roosevelt_full_book.parent,
            enable_checkpoints=False
        )

        # Test page with context
        prev_text, current_data, next_text = corrector.get_page_context(
            page_num=50,
            total_pages=636
        )

        assert current_data is not None
        assert current_data['page_number'] == 50
        # Should have context from adjacent pages
        assert prev_text is not None or next_text is not None


# ============================================================================
# JSON EXTRACTION TESTS
# ============================================================================

@pytest.mark.unit
class TestJSONExtraction:
    """Test JSON extraction from LLM responses."""

    def test_extract_json_from_code_block(self, tmp_path):
        """Test extracting JSON from markdown code blocks."""
        # Create test book directory
        book_dir = tmp_path / "test"
        book_dir.mkdir()

        corrector = StructuredPageCorrector(
            book_title="test",
            storage_root=tmp_path,
            enable_checkpoints=False
        )

        response = '''```json
{
  "page_number": 1,
  "total_errors_found": 2,
  "errors": []
}
```'''

        extracted = corrector.extract_json(response)
        data = json.loads(extracted)
        assert data['page_number'] == 1
        assert data['total_errors_found'] == 2

    def test_extract_json_with_trailing_comma(self, tmp_path):
        """Test fixing trailing commas in JSON."""
        # Create test book directory
        book_dir = tmp_path / "test"
        book_dir.mkdir()

        corrector = StructuredPageCorrector(
            book_title="test",
            storage_root=tmp_path,
            enable_checkpoints=False
        )

        response = '''
{
  "page_number": 1,
  "errors": [
    {"id": 1},
  ]
}
'''

        extracted = corrector.extract_json(response)
        data = json.loads(extracted)
        assert data['page_number'] == 1

    def test_extract_json_plain(self, tmp_path):
        """Test extracting plain JSON."""
        # Create test book directory
        book_dir = tmp_path / "test"
        book_dir.mkdir()

        corrector = StructuredPageCorrector(
            book_title="test",
            storage_root=tmp_path,
            enable_checkpoints=False
        )

        response = '{"page_number": 1, "total_errors_found": 0, "errors": []}'

        extracted = corrector.extract_json(response)
        data = json.loads(extracted)
        assert data['page_number'] == 1


# ============================================================================
# AGENT TESTS (Real API Calls)
# ============================================================================

@pytest.mark.api
@pytest.mark.integration
class TestAgent1ErrorDetection:
    """Test Agent 1 error detection with real API calls."""

    def test_agent1_detects_errors(self, temp_test_book):
        """Test Agent 1 finds OCR errors in real text."""
        corrector = StructuredPageCorrector(
            book_title=temp_test_book.name,
            storage_root=temp_test_book.parent,
            model="openai/gpt-4o-mini",
            max_workers=1,
            calls_per_minute=60,
            enable_checkpoints=False
        )

        # Load a page with OCR errors
        page_num = 10
        prev_text, page_data, next_text = corrector.get_page_context(
            page_num, total_pages=12
        )

        assert page_data is not None, "Page data should be available from temp_test_book fixture"

        # Run Agent 1
        error_catalog = corrector.agent1_detect_errors(
            page_num, prev_text, page_data, next_text
        )

        # Verify output structure
        assert 'page_number' in error_catalog
        assert 'total_errors_found' in error_catalog
        assert 'errors' in error_catalog
        assert error_catalog['page_number'] == page_num
        assert isinstance(error_catalog['errors'], list)

    def test_agent1_handles_empty_page(self, temp_test_book):
        """Test Agent 1 handles pages with no correctable content."""
        corrector = StructuredPageCorrector(
            book_title=temp_test_book.name,
            storage_root=temp_test_book.parent,
            model="openai/gpt-4o-mini",
            enable_checkpoints=False
        )

        # Create a page with only images
        page_data = {
            "page_number": 1,
            "regions": [
                {"type": "image", "bbox": [0, 0, 100, 100]},
                {"type": "footer", "text": "Page 1", "bbox": [0, 900, 100, 20]}
            ]
        }

        error_catalog = corrector.agent1_detect_errors(
            1, None, page_data, None
        )

        assert error_catalog['total_errors_found'] == 0


@pytest.mark.api
@pytest.mark.integration
class TestAgent2Correction:
    """Test Agent 2 correction application with real API calls."""

    def test_agent2_applies_corrections(self, temp_test_book):
        """Test Agent 2 applies corrections based on error catalog."""
        corrector = StructuredPageCorrector(
            book_title=temp_test_book.name,
            storage_root=temp_test_book.parent,
            model="openai/gpt-4o-mini",
            enable_checkpoints=False
        )

        # Create a simple page and error catalog
        page_data = {
            "page_number": 1,
            "regions": [
                {
                    "type": "body",
                    "text": "The presidnet walked into tbe room.",
                    "bbox": [0, 0, 100, 20]
                }
            ]
        }

        error_catalog = {
            "page_number": 1,
            "total_errors_found": 2,
            "errors": [
                {
                    "error_id": 1,
                    "original_text": "presidnet",
                    "suggested_correction": "president",
                    "error_type": "typo",
                    "confidence": 0.95
                },
                {
                    "error_id": 2,
                    "original_text": "tbe",
                    "suggested_correction": "the",
                    "error_type": "character_substitution",
                    "confidence": 0.98
                }
            ]
        }

        corrected_text = corrector.agent2_correct(1, page_data, error_catalog)

        assert isinstance(corrected_text, str)
        # Should contain correction markers
        assert "[CORRECTED:" in corrected_text

    def test_agent2_no_corrections_needed(self, temp_test_book):
        """Test Agent 2 returns original text when no errors found."""
        corrector = StructuredPageCorrector(
            book_title=temp_test_book.name,
            storage_root=temp_test_book.parent,
            enable_checkpoints=False
        )

        page_data = {
            "page_number": 1,
            "regions": [
                {
                    "type": "body",
                    "text": "This is perfect text.",
                    "bbox": [0, 0, 100, 20]
                }
            ]
        }

        error_catalog = {
            "page_number": 1,
            "total_errors_found": 0,
            "errors": []
        }

        corrected_text = corrector.agent2_correct(1, page_data, error_catalog)

        assert corrected_text == "This is perfect text."


@pytest.mark.api
@pytest.mark.integration
class TestAgent3Verification:
    """Test Agent 3 verification with real API calls."""

    def test_agent3_verifies_corrections(self, temp_test_book):
        """Test Agent 3 verifies applied corrections."""
        corrector = StructuredPageCorrector(
            book_title=temp_test_book.name,
            storage_root=temp_test_book.parent,
            model="openai/gpt-4o-mini",
            enable_checkpoints=False
        )

        page_data = {
            "page_number": 1,
            "regions": [
                {
                    "type": "body",
                    "text": "The presidnet walked.",
                    "bbox": [0, 0, 100, 20]
                }
            ]
        }

        error_catalog = {
            "errors": [
                {
                    "error_id": 1,
                    "original_text": "presidnet",
                    "suggested_correction": "president"
                }
            ]
        }

        corrected_text = "The president[CORRECTED:1] walked."

        verification = corrector.agent3_verify(
            1, page_data, error_catalog, corrected_text
        )

        # Verify output structure
        assert 'page_number' in verification
        assert 'confidence_score' in verification
        assert 'needs_human_review' in verification
        assert isinstance(verification['confidence_score'], (int, float))


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

@pytest.mark.api
@pytest.mark.integration
class TestCorrectionIntegration:
    """Test full correction pipeline integration."""

    def test_process_single_page_end_to_end(self, temp_test_book):
        """Test processing a single page through all 3 agents."""
        corrector = StructuredPageCorrector(
            book_title=temp_test_book.name,
            storage_root=temp_test_book.parent,
            model="openai/gpt-4o-mini",
            max_workers=1,
            enable_checkpoints=False
        )

        result = corrector.process_single_page(page_num=10, total_pages=12)

        # Verify result structure
        assert 'page' in result
        assert 'status' in result
        assert result['page'] == 10

        # Should have created output file
        output_file = temp_test_book / "corrected" / "page_0010.json"
        assert output_file.exists()

        # Verify output structure
        with open(output_file) as f:
            corrected_data = json.load(f)

        assert 'page_number' in corrected_data
        assert 'llm_processing' in corrected_data
        assert 'error_catalog' in corrected_data['llm_processing']
        assert 'verification' in corrected_data['llm_processing']

    def test_process_multiple_pages(self, temp_test_book):
        """Test processing multiple pages in parallel."""
        corrector = StructuredPageCorrector(
            book_title=temp_test_book.name,
            storage_root=temp_test_book.parent,
            model="openai/gpt-4o-mini",
            max_workers=2,
            calls_per_minute=60,
            enable_checkpoints=False
        )

        # Process pages 10-11
        corrector.process_pages(
            start_page=10,
            end_page=11,
            total_pages=12,
            resume=False
        )

        # Verify both pages were processed
        for page_num in [10, 11]:
            output_file = temp_test_book / "corrected" / f"page_{page_num:04d}.json"
            assert output_file.exists()

    def test_cost_tracking(self, temp_test_book):
        """Test that API costs are tracked."""
        corrector = StructuredPageCorrector(
            book_title=temp_test_book.name,
            storage_root=temp_test_book.parent,
            model="openai/gpt-4o-mini",
            max_workers=1,
            enable_checkpoints=False
        )

        corrector.process_single_page(page_num=10, total_pages=12)

        # Should have tracked some cost
        assert corrector.stats['total_cost_usd'] > 0


# ============================================================================
# CHECKPOINT TESTS
# ============================================================================

@pytest.mark.unit
class TestCorrectionCheckpoints:
    """Test checkpoint integration."""

    def test_checkpoint_enabled(self, temp_test_book):
        """Test that checkpoints can be enabled."""
        corrector = StructuredPageCorrector(
            book_title=temp_test_book.name,
            storage_root=temp_test_book.parent,
            enable_checkpoints=True
        )

        assert corrector.checkpoint is not None
        assert corrector.checkpoint.stage == "correction"

    @pytest.mark.api
    def test_resume_from_checkpoint(self, temp_test_book):
        """Test resuming from checkpoint skips completed pages."""
        # Process page 10
        corrector1 = StructuredPageCorrector(
            book_title=temp_test_book.name,
            storage_root=temp_test_book.parent,
            model="openai/gpt-4o-mini",
            enable_checkpoints=True
        )
        corrector1.process_pages(start_page=10, end_page=10, total_pages=12)

        initial_cost = corrector1.stats['total_cost_usd']

        # Resume - should skip page 10
        corrector2 = StructuredPageCorrector(
            book_title=temp_test_book.name,
            storage_root=temp_test_book.parent,
            model="openai/gpt-4o-mini",
            enable_checkpoints=True
        )
        corrector2.process_pages(start_page=10, end_page=10, total_pages=12, resume=True)

        # Should not incur additional cost for page 10
        assert corrector2.stats['total_cost_usd'] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "not api"])
